"""Claims, proof bundles and verifications (API-03; ZK-06 procedure from sigil.verify).

  verifier: POST /claims {registration_id, suspect_artifact_id}   -> sigil.records.make_claim (fresh nonce)
  owner:    POST /claims/{id}/proofs  (proof.json + public.json from `sigil prove`; proving needs the seed,
            which never leaves the owner, so proofs are generated client-side)
  verifier: POST /verifications {proof_id} -> sigil.verify.verify_ownership, persisted with every named reason

The suspect's Uchida vector is recomputed by the verifier from the stored suspect file with the SDK adapters
(sigil.adapters.uchida_vector). TODO(M4): until sigil.adapters lands, the request must supply the vector
(`suspect_vector`); such verifications are recorded with vector_source = "request" and flagged in reports.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from sigil.protocol import PUBLIC_SIGNALS, Config
from sigil.records import make_claim
from sigil.verify import verify_ownership

from .. import audit
from ..auth import actor, current_user, get_db, require
from ..models import Claim, ModelArtifact, Proof, Registration, User, Verification
from ..monitor import sha256_file
from ..problems import ProblemError, responses
from . import schemas as S
from .common import Page, claim_out, ensure_owns_owner, get_or_404, proof_out, verification_out

router = APIRouter()
MAX_PROOF_FILE = 1024 * 1024


# ---------------------------------------------------------------------------------------------- claims
@router.post("/claims", response_model=S.ClaimOut, status_code=201, tags=["claims and proofs"],
             responses=responses(401, 403, 404, 422),
             summary="Open a claim about a suspect model (fresh nonce; sigil.records.make_claim)")
def open_claim(body: S.ClaimCreate, user: User = Depends(require("verifier")), db: Session = Depends(get_db)):
    reg = get_or_404(db, Registration, body.registration_id, "registration")
    art = get_or_404(db, ModelArtifact, body.suspect_artifact_id, "artifact")
    if reg.receipt is None:
        raise ProblemError(422, "the registration has no registry receipt")
    rec = json.loads(reg.registration_json)
    claim = make_claim(rec, art.sha256)
    while claim["opened_at"] <= reg.receipt.registered_at:     # a claim must be strictly later than the receipt
        time.sleep(0.2)
        claim = make_claim(rec, art.sha256)
    row = Claim(claim_uuid=claim["claim_id"], registration_id=reg.id, suspect_artifact_id=art.id,
                claim_json=json.dumps(claim, sort_keys=True), nonce=claim["nonce"], opened_at=claim["opened_at"],
                opened_by=user.id)
    db.add(row)
    db.flush()
    audit.append(db, actor(user), "claim.opened", "claim", row.id,
                 {"claim_id": claim["claim_id"], "registration_id": reg.id, "suspect_sha256": art.sha256})
    return claim_out(row)


@router.get("/claims", summary="List claims", response_model=list[S.ClaimOut], tags=["claims and proofs"], responses=responses(401))
def list_claims(page: Page = Depends(), registration_id: int | None = None, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    q = select(Claim).order_by(Claim.id)
    if registration_id is not None:
        q = q.where(Claim.registration_id == registration_id)
    return [claim_out(c) for c in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/claims/{claim_id}", summary="One claim (the owner needs its nonce to prove)", response_model=S.ClaimOut, tags=["claims and proofs"], responses=responses(401, 404))
def get_claim(claim_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return claim_out(get_or_404(db, Claim, claim_id, "claim"))


# ---------------------------------------------------------------------------------------------- proofs
def _check_bundle(proof, public) -> list[str]:
    if not isinstance(proof, dict) or not proof:
        raise ProblemError(422, "proof.json must be a non-empty JSON object")
    if not isinstance(public, list) or not all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in public):
        raise ProblemError(422, "public.json must be a list of decimal strings")
    if len(public) != len(PUBLIC_SIGNALS):
        raise ProblemError(422, f"public.json must have {len(PUBLIC_SIGNALS)} signals: {', '.join(PUBLIC_SIGNALS)}")
    return [str(x) for x in public]


def _save_proof(db: Session, user: User, claim: Claim, proof: dict, public: list[str]) -> dict:
    ensure_owns_owner(user, claim.registration.owner)
    proof_json = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    p = Proof(claim_id=claim.id, proof_json=proof_json, public_json=json.dumps(public),
              proof_sha256=hashlib.sha256(proof_json.encode()).hexdigest(), submitted_by=user.id)
    db.add(p)
    db.flush()
    audit.append(db, actor(user), "proof.submitted", "proof", p.id, {"claim_id": claim.claim_uuid,
                                                                     "proof_sha256": p.proof_sha256})
    return proof_out(p)


@router.post("/claims/{claim_id}/proofs", response_model=S.ProofOut, status_code=201, tags=["claims and proofs"],
             responses=responses(401, 403, 404, 422), summary="Submit a proof bundle for a claim (JSON)")
def submit_proof(claim_id: int, body: S.ProofCreate, user: User = Depends(require("owner")),
                 db: Session = Depends(get_db)):
    claim = get_or_404(db, Claim, claim_id, "claim")
    return _save_proof(db, user, claim, body.proof, _check_bundle(body.proof, body.public))


@router.post("/claims/{claim_id}/proofs/upload", response_model=S.ProofOut, status_code=201,
             tags=["claims and proofs"], responses=responses(401, 403, 404, 413, 422),
             summary="Submit a proof bundle as files (proof.json, public.json, optional claim.json)")
def upload_proof(claim_id: int, proof: UploadFile = File(...), public: UploadFile = File(...),
                 claim_file: UploadFile | None = File(None, alias="claim"), user: User = Depends(require("owner")),
                 db: Session = Depends(get_db)):
    claim = get_or_404(db, Claim, claim_id, "claim")

    def load(f: UploadFile, what: str):
        raw = f.file.read(MAX_PROOF_FILE + 1)
        if len(raw) > MAX_PROOF_FILE:
            raise ProblemError(413, f"{what} is larger than {MAX_PROOF_FILE} bytes")
        try:
            return json.loads(raw)
        except ValueError as e:
            raise ProblemError(422, f"{what} is not valid JSON") from e

    p, pub = load(proof, "proof.json"), load(public, "public.json")
    if claim_file is not None:
        c = load(claim_file, "claim.json")
        if not isinstance(c, dict) or c.get("claim_id") != claim.claim_uuid or c.get("nonce") != claim.nonce:
            raise ProblemError(422, "claim.json is not this claim (claim_id or nonce differ)")
    return _save_proof(db, user, claim, p, _check_bundle(p, pub))


@router.get("/proofs/{proof_id}", summary="One proof bundle's metadata", response_model=S.ProofOut, tags=["claims and proofs"], responses=responses(401, 404))
def get_proof(proof_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return proof_out(get_or_404(db, Proof, proof_id, "proof"))


@router.get("/proofs/{proof_id}/bundle", tags=["claims and proofs"], responses=responses(401, 404),
            summary="Download the bundle (proof.json, public.json, claim.json) as one JSON document")
def proof_bundle(proof_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = get_or_404(db, Proof, proof_id, "proof")
    return {"proof.json": json.loads(p.proof_json), "public.json": json.loads(p.public_json),
            "claim.json": json.loads(p.claim.claim_json),
            "registration.json": json.loads(p.claim.registration.registration_json),
            "receipt.json": json.loads(p.claim.registration.receipt.receipt_json) if p.claim.registration.receipt else None}


# ---------------------------------------------------------------------------------------------- verifications
def suspect_vector(settings, art: ModelArtifact, cfg: Config, supplied):
    """(vector, source). The verifier recomputes it from the file with the SDK adapters when they exist."""
    try:
        from sigil.adapters import uchida_vector          # M4 (WM-03..05); safe loaders only
    except ImportError:
        uchida_vector = None
    if uchida_vector is not None:
        try:
            return uchida_vector(str(Path(settings.uploads) / art.stored_path), cfg.layer), "sdk_adapter"
        except Exception as e:  # noqa: BLE001 - reported as a 422, not a crash
            raise ProblemError(422, f"could not extract layer {cfg.layer!r} from the suspect model: "
                                    f"{e.__class__.__name__}: {str(e)[:200]}") from e
    # TODO(M4): remove this branch once sigil.adapters is installed. A vector supplied by the caller is not
    # recomputed from the suspect file; the certificate says so.
    if supplied is None:
        raise ProblemError(422, "suspect_vector is required: the SDK adapters (sigil.adapters) are not installed "
                                "yet, so the server cannot read the layer from the file (TODO M4)")
    return supplied, "request"


def snark_checker(app, cfg: Config, proof: dict, public: list[str], notes: list[str]):
    injected = getattr(app.state, "snark_verifier", None)
    if injected is not None:
        return lambda: bool(injected(cfg, proof, public))

    def check() -> bool:
        try:
            from sigil.zk.circom import ZkError, artifacts, verify_snark
            vkey = artifacts(cfg).vkey
            if not vkey.exists():
                notes.append(f"the zk-SNARK was not checked: no verification key for circuit {vkey.name}")
                return False
            return verify_snark(vkey, proof, public)
        except (ZkError, OSError, subprocess.SubprocessError) as e:
            notes.append(f"the zk-SNARK was not checked: ZK toolchain unavailable ({str(e).splitlines()[0][:160]})")
            return False
    return check


@router.post("/verifications", response_model=S.VerificationOut, status_code=201, tags=["verifications"],
             responses=responses(401, 403, 404, 409, 422),
             summary="Verify a proof bundle against the suspect model; the verdict and reasons are persisted")
def verify(body: S.VerificationCreate, request: Request, user: User = Depends(require("verifier")),
           db: Session = Depends(get_db)):
    s = request.app.state.settings
    proof = get_or_404(db, Proof, body.proof_id, "proof")
    claim = proof.claim
    reg = claim.registration
    art = claim.suspect
    if reg.receipt is None:
        raise ProblemError(422, "the registration has no registry receipt")
    path = Path(s.uploads) / art.stored_path
    if not path.is_file():
        raise ProblemError(409, "the stored suspect model file is missing")
    observed = sha256_file(path)                         # recomputed by the verifier, not taken from the DB
    rec, rcp = json.loads(reg.registration_json), json.loads(reg.receipt.receipt_json)
    cfg = Config.from_dict(rec["config"])
    vector, source = suspect_vector(s, art, cfg, body.suspect_vector)
    proof_doc, public = json.loads(proof.proof_json), json.loads(proof.public_json)
    notes: list[str] = []
    verdict = verify_ownership(proof=proof_doc, public=public, registration=rec, receipt=rcp,
                               claim=json.loads(claim.claim_json), suspect_w=vector, suspect_model_sha256=observed,
                               trusted_registry_keys=set(request.app.state.registry.trusted),
                               snark_verifier=snark_checker(request.app, cfg, proof_doc, public, notes))
    reasons = verdict.reasons + notes
    if source == "request":
        verdict.checks["suspect_vector_from_file"] = False
    v = Verification(proof_id=proof.id, claim_id=claim.id, accepted=verdict.accepted, reasons=reasons,
                     verdict={**verdict.to_dict(), "reasons": reasons, "notes": notes,
                              "registration_sha256": claim.registration.registration_sha256},
                     vector_source=source, suspect_sha256=observed, verified_by=user.id)
    db.add(v)
    db.flush()
    audit.append(db, actor(user), "verification.completed", "verification", v.id,
                 {"accepted": v.accepted, "claim_id": claim.claim_uuid, "reasons": len(reasons),
                  "vector_source": source})
    return verification_out(v)


@router.get("/verifications", summary="Verification history (filter by claim or verdict)", response_model=list[S.VerificationOut], tags=["verifications"], responses=responses(401))
def list_verifications(page: Page = Depends(), claim_id: int | None = None, accepted: bool | None = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Verification).order_by(Verification.id)
    if claim_id is not None:
        q = q.where(Verification.claim_id == claim_id)
    if accepted is not None:
        q = q.where(Verification.accepted.is_(accepted))
    return [verification_out(v) for v in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/verifications/{verification_id}", summary="One verification: verdict, named reasons, checks", response_model=S.VerificationOut, tags=["verifications"],
            responses=responses(401, 404))
def get_verification(verification_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return verification_out(get_or_404(db, Verification, verification_id, "verification"))

