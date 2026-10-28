"""Registrations and registry receipts (API-03, CR-02, CR-03).

An owner submits the record `sigil register` wrote. The server re-verifies it with
sigil.records.verify_registration (every derived field and the owner signature), then the REGISTRY key issues
a receipt (sigil.records.make_receipt): a signed statement that it saw this exact record at this time. In a
dispute, the earliest valid registration of the same model wins (sigil.records.earliest).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sigil.protocol import Config
from sigil.records import RECEIPT_SCHEMA, canonical_json, earliest, make_receipt, registration_hash, sha256_hex, \
    verify_receipt, verify_registration

from .. import audit
from ..auth import actor, current_user, get_db, require
from ..models import ModelArtifact, Owner, Receipt, Registration, User, WatermarkConfig
from ..problems import ProblemError, responses
from . import schemas as S
from .common import Page, ensure_owns_owner, get_or_404, registration_out

router = APIRouter(tags=["registry"])


def upsert_config(db: Session, cfg_dict: dict) -> WatermarkConfig:
    from sigil.protocol import config_hash
    try:
        cfg = Config.from_dict(cfg_dict)
    except (KeyError, TypeError, ValueError) as e:
        raise ProblemError(422, f"invalid watermark config: {e}") from e
    h = str(config_hash(cfg))
    row = db.scalar(select(WatermarkConfig).where(WatermarkConfig.config_hash == h))
    if row is None:
        d = cfg.to_dict()
        row = WatermarkConfig(config_hash=h, protocol=d["protocol"], T=cfg.T, M=cfg.M, layer=cfg.layer,
                              scale_bits=cfg.scale_bits, w_bits=cfg.w_bits, max_err=cfg.max_err, norm=cfg.norm, config=d)
        db.add(row)
        db.flush()
    return row


@router.get("/registry", response_model=S.RegistryInfo, summary="The registry's public key and dispute rule")
def registry_info(request: Request):
    reg = request.app.state.registry
    return {"registry_public_key": reg.public_key, "trusted_registry_keys": sorted(reg.trusted),
            "receipt_schema": RECEIPT_SCHEMA,
            "dispute_rule": "among valid registrations of the same model_sha256, the earliest receipt "
                            "(registered_at) wins"}


@router.post("/registrations", response_model=S.RegistrationOut, status_code=201,
             responses=responses(401, 403, 404, 409, 422),
             summary="Submit an owner-signed registration (from `sigil register`); the registry timestamps it")
def submit_registration(record: S.RegistrationRecord, request: Request, user: User = Depends(require("owner")),
                        db: Session = Depends(get_db)):
    rec = record.model_dump(by_alias=True)
    problems = verify_registration(rec)
    if problems:
        raise ProblemError(422, "the registration does not verify", title="Invalid registration", problems=problems)
    owner = db.scalar(select(Owner).where(Owner.public_key_hex == rec["owner_public_key"].lower()))
    if owner is None:
        raise ProblemError(422, "register this owner public key first (POST /api/v2/owners)")
    ensure_owns_owner(user, owner)
    rhash = registration_hash(rec)
    if db.scalar(select(Registration.id).where(Registration.registration_sha256 == rhash)):
        raise ProblemError(409, "this registration was already submitted")
    cfg_row = upsert_config(db, rec["config"])
    artifact = db.scalar(select(ModelArtifact).where(ModelArtifact.sha256 == rec["model_sha256"].lower())
                         .order_by(ModelArtifact.id).limit(1))
    receipt = make_receipt(request.app.state.registry.key, rec)
    reg = Registration(owner_id=owner.id, watermark_config_id=cfg_row.id,
                       model_artifact_id=artifact.id if artifact else None,
                       registration_json=canonical_json(rec).decode("utf-8"), registration_sha256=rhash,
                       commitment=rec["commitment"], model_sha256=rec["model_sha256"].lower(),
                       owner_created_at=rec["created_at"], submitted_by=user.id)
    rjson = canonical_json(receipt).decode("utf-8")
    reg.receipt = Receipt(receipt_json=rjson, receipt_sha256=sha256_hex(rjson.encode()),
                          registered_at=receipt["registered_at"], registry_public_key=receipt["registry_public_key"])
    db.add(reg)
    db.flush()
    audit.append(db, actor(user), "registration.created", "registration", reg.id,
                 {"registration_sha256": rhash, "commitment": reg.commitment, "model_sha256": reg.model_sha256,
                  "registered_at": receipt["registered_at"]})
    return registration_out(reg)


@router.get("/registrations", summary="List registrations with their receipts (filter by model_sha256 or owner)", response_model=list[S.RegistrationOut], responses=responses(401))
def list_registrations(page: Page = Depends(), model_sha256: str | None = None, owner_id: int | None = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Registration).options(selectinload(Registration.receipt)).order_by(Registration.id)
    if model_sha256:
        q = q.where(Registration.model_sha256 == model_sha256.lower())
    if owner_id is not None:
        q = q.where(Registration.owner_id == owner_id)
    return [registration_out(r) for r in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/registrations/earliest", response_model=S.EarliestOut, responses=responses(401, 422),
            summary="Dispute rule (CR-03): the earliest valid registration of a model")
def earliest_registration(request: Request, model_sha256: str = Query(pattern=r"^[0-9a-fA-F]{64}$"),
                          user: User = Depends(current_user), db: Session = Depends(get_db)):
    trusted = request.app.state.registry.trusted
    rows = db.scalars(select(Registration).options(selectinload(Registration.receipt))
                      .where(Registration.model_sha256 == model_sha256.lower())).all()
    pairs = []
    for r in rows:
        if r.receipt is None:
            continue
        rec, rcp = json.loads(r.registration_json), json.loads(r.receipt.receipt_json)
        if not verify_registration(rec) and not verify_receipt(rcp, rec, trusted):
            pairs.append((rec, rcp, r))
    win = earliest([(rec, rcp) for rec, rcp, _ in pairs])
    winner = next((r for rec, rcp, r in pairs if win is not None and rec is win[0]), None)
    return {"model_sha256": model_sha256.lower(), "candidates": len(pairs),
            "winner": registration_out(winner) if winner else None}


@router.get("/registrations/{registration_id}", summary="One registration with its registry receipt", response_model=S.RegistrationOut, responses=responses(401, 404))
def get_registration(registration_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return registration_out(get_or_404(db, Registration, registration_id, "registration"))
