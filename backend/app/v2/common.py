"""Helpers shared by the v2 routers: lookups, serialisers and ownership checks."""
from __future__ import annotations

import json

from fastapi import Query
from sqlalchemy.orm import Session

from ..models import (ApiToken, AttackRun, Claim, Deployment, DeploymentCheck, ModelArtifact, Owner, Proof,
                      Registration, User, Verification)
from ..problems import ProblemError


class Page:
    def __init__(self, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        self.limit, self.offset = limit, offset


def get_or_404(db: Session, model, ident, what: str):
    row = db.get(model, ident)
    if row is None:
        raise ProblemError(404, f"{what} {ident} not found")
    return row


def is_admin(user: User) -> bool:
    return user.role == "admin"


def ensure_owns_owner(user: User, owner: Owner) -> None:
    if not is_admin(user) and owner.user_id != user.id:
        raise ProblemError(403, "this owner key belongs to another account")


# ---------------------------------------------------------------------------------------------- serialisers
def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active, "created_at": u.created_at}


def token_info(t: ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "created_at": t.created_at, "last_used_at": t.last_used_at,
            "expires_at": t.expires_at, "revoked_at": t.revoked_at}


def owner_out(o: Owner) -> dict:
    return {"id": o.id, "label": o.label, "public_key": o.public_key_hex, "pk_hash": o.pk_hash, "user_id": o.user_id,
            "created_at": o.created_at}


def artifact_out(a: ModelArtifact) -> dict:
    return {"id": a.id, "model_id": a.model_id, "filename": a.filename, "sha256": a.sha256, "size_bytes": a.size_bytes,
            "framework": a.framework, "extension": a.extension, "created_at": a.created_at}


def model_out(m) -> dict:
    return {"id": m.id, "name": m.name, "description": m.description, "purpose": m.purpose, "created_by": m.created_by,
            "created_at": m.created_at, "artifacts": [artifact_out(a) for a in m.artifacts]}


def registration_out(r: Registration) -> dict:
    rec = json.loads(r.registration_json)
    rcp = json.loads(r.receipt.receipt_json) if r.receipt else None
    return {"id": r.id, "owner_id": r.owner_id, "model_artifact_id": r.model_artifact_id,
            "registration_sha256": r.registration_sha256, "commitment": r.commitment, "model_sha256": r.model_sha256,
            "config_hash": rec.get("config_hash"), "owner_created_at": r.owner_created_at,
            "registered_at": r.receipt.registered_at if r.receipt else None, "registration": rec, "receipt": rcp,
            "created_at": r.created_at}


def claim_out(c: Claim) -> dict:
    return {"id": c.id, "claim_id": c.claim_uuid, "registration_id": c.registration_id,
            "suspect_artifact_id": c.suspect_artifact_id, "nonce": c.nonce, "opened_at": c.opened_at,
            "claim": json.loads(c.claim_json), "created_at": c.created_at}


def proof_out(p: Proof) -> dict:
    return {"id": p.id, "claim_id": p.claim_id, "proof_sha256": p.proof_sha256,
            "public": [str(x) for x in json.loads(p.public_json)], "created_at": p.created_at}


def verification_out(v: Verification) -> dict:
    return {"id": v.id, "proof_id": v.proof_id, "claim_id": v.claim_id, "accepted": v.accepted, "reasons": v.reasons,
            "checks": (v.verdict or {}).get("checks", {}), "vector_source": v.vector_source,
            "suspect_sha256": v.suspect_sha256, "created_at": v.created_at}


def attack_run_out(r: AttackRun, with_results: bool = False) -> dict:
    out = {"id": r.id, "job_id": r.job_id, "source": r.source, "commitment": r.commitment, "threshold": r.threshold,
           "simulated": r.simulated, "results_sha256": r.results_sha256, "created_at": r.created_at,
           "total": len(r.results), "survived": sum(1 for x in r.results if x.survives)}
    if with_results:
        out["results"] = [{"attack": x.attack, "family": x.family, "accuracy": x.accuracy, "owner_ber": x.owner_ber,
                           "survives": x.survives} for x in r.results]
    return out


def deployment_out(d: Deployment) -> dict:
    return {"id": d.id, "name": d.name, "environment": d.environment, "artifact_path": d.artifact_path,
            "expected_sha256": d.expected_sha256, "model_artifact_id": d.model_artifact_id, "active": d.active,
            "last_status": d.last_status, "last_checked_at": d.last_checked_at, "created_at": d.created_at}


def check_out(c: DeploymentCheck) -> dict:
    return {"id": c.id, "deployment_id": c.deployment_id, "checked_at": c.checked_at, "trigger": c.trigger,
            "status": c.status, "alert": c.alert, "expected_sha256": c.expected_sha256,
            "observed_sha256": c.observed_sha256, "registered": c.registered, "detail": c.detail}
