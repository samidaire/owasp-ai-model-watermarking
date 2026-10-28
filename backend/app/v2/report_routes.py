"""Audit log, reports and system endpoints (DB-03, API-08, health/environment)."""
from __future__ import annotations

import json
import platform
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import __version__, audit, reports
from ..auth import current_user, get_db, require
from ..models import AuditEvent, User, Verification
from ..problems import ProblemError, responses
from ..registry import verify_document
from . import schemas as S
from .common import Page, get_or_404

router = APIRouter()
PDF = {200: {"content": {"application/pdf": {}}, "description": "PDF document"}}


# ---------------------------------------------------------------------------------------------- audit
@router.get("/audit/events", summary="Audit events in chain order", response_model=list[S.AuditEventOut], tags=["audit"], responses=responses(401, 403))
def list_events(page: Page = Depends(), action: str | None = None, after_seq: int = Query(0, ge=0),
                user: User = Depends(require("verifier")), db: Session = Depends(get_db)):
    q = select(AuditEvent).where(AuditEvent.seq > after_seq).order_by(AuditEvent.seq)
    if action:
        q = q.where(AuditEvent.action == action)
    return [audit.event_dict(e) for e in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/audit/verify", response_model=S.ChainStatus, tags=["audit"], responses=responses(401, 403, 422),
            summary="Re-check the whole hash chain (optionally against a previously exported signed head)")
def verify_chain(anchor_seq: int | None = Query(None, ge=1), anchor_hash: str | None = Query(None, pattern=r"^[0-9a-f]{64}$"),
                 user: User = Depends(require("verifier")), db: Session = Depends(get_db)):
    if (anchor_seq is None) != (anchor_hash is None):
        raise ProblemError(422, "give both anchor_seq and anchor_hash, or neither")
    return audit.verify_chain(db, (anchor_seq, anchor_hash) if anchor_seq else None)


@router.get("/audit/head", response_model=S.SignedDocument, tags=["audit"], responses=responses(401, 403),
            summary="The chain head (seq, hash), signed by the registry: keep it to detect a later rewrite")
def chain_head(request: Request, user: User = Depends(require("verifier")), db: Session = Depends(get_db)):
    return reports.audit_head(db, request.app.state.registry)


@router.get("/audit/export", tags=["audit", "reports"], responses={**responses(401, 403), 200: {
    "content": {"application/json": {}, "text/csv": {}},
    "description": "JSON: signed export with every event and the chain status. CSV: one row per event; the "
                   "signed chain head is in the X-Sigil-Chain-Head header."}},
            summary="Audit export (JSON or CSV) with the hash-chain proof")
def export(request: Request, format: Literal["json", "csv"] = "json", user: User = Depends(require("verifier")),
           db: Session = Depends(get_db)):
    reg = request.app.state.registry
    if format == "csv":
        body, head = reports.audit_export_csv(db, reg)
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="sigil-audit.csv"',
                                 "X-Sigil-Chain-Head": json.dumps(head, separators=(",", ":")),
                                 "Cache-Control": "no-store"})
    return JSONResponse(reports.audit_export_json(db, reg),
                        headers={"Content-Disposition": 'attachment; filename="sigil-audit.json"'})


# ---------------------------------------------------------------------------------------------- reports
@router.get("/verifications/{verification_id}/certificate", response_model=S.SignedDocument, tags=["reports"],
            responses=responses(401, 404), summary="Ownership certificate as registry-signed JSON")
def certificate_json(verification_id: int, request: Request, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    v = get_or_404(db, Verification, verification_id, "verification")
    return reports.certificate(db, request.app.state.registry, v)


@router.get("/verifications/{verification_id}/certificate.pdf", tags=["reports"],
            responses={**responses(401, 404), **PDF}, summary="Ownership certificate as PDF")
def certificate_pdf(verification_id: int, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    v = get_or_404(db, Verification, verification_id, "verification")
    pdf = reports.certificate_pdf(reports.certificate(db, request.app.state.registry, v))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="sigil-certificate-{v.id}.pdf"'})


@router.get("/reports/compliance", response_model=S.SignedDocument, tags=["reports"], responses=responses(401),
            summary="Compliance report: evidence mapped to OWASP #MODEL WATERMARKING and REQUIREMENTS IDs")
def compliance(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return reports.compliance(db, request.app.state.registry)


@router.get("/reports/compliance.pdf", summary="Compliance report as PDF", tags=["reports"], responses={**responses(401), **PDF})
def compliance_pdf(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    pdf = reports.compliance_pdf(reports.compliance(db, request.app.state.registry))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="sigil-compliance.pdf"'})


@router.post("/reports/verify-signature", response_model=S.SignatureCheck, tags=["reports"], responses=responses(401),
             summary="Check a registry-signed document (certificate, report, export, head)")
def verify_signature(body: S.SignatureCheckRequest, request: Request, user: User = Depends(current_user)):
    problems = verify_document(body.document, request.app.state.registry.trusted)
    return {"valid": not problems, "problems": problems}


# ---------------------------------------------------------------------------------------------- system
@router.get("/health", response_model=S.Health, tags=["system"], summary="Liveness and database check (no auth)")
def health(request: Request):
    try:
        with request.app.state.sessionmaker() as db:
            db.execute(text("SELECT 1"))
        dbs = "ok"
    except Exception:  # noqa: BLE001
        dbs = "error"
    return {"status": "ok" if dbs == "ok" else "degraded", "database": dbs, "version": __version__, "api_version": 2}


@router.get("/environment", tags=["system"], responses=responses(401),
            summary="Mode, GPU probe, SDK, ZK toolchain and storage facts (no paths outside the repo, no secrets)")
def environment(request: Request, user: User = Depends(current_user)):
    from .. import legacy
    import sigil
    s = request.app.state.settings
    try:
        import sigil.adapters  # noqa: F401
        from sigil.adapters import uchida_vector  # noqa: F401
        adapters = True
    except ImportError:
        adapters = False
    zk = {"circuits": None, "demo_zkey": False, "demo_vkey": False}
    try:
        from sigil.protocol import Config
        from sigil.zk.circom import artifacts, circuits_dir
        a = artifacts(Config())
        zk = {"circuits": legacy.rel(circuits_dir()), "demo_zkey": a.zkey.exists(), "demo_vkey": a.vkey.exists()}
    except Exception:  # noqa: BLE001 - toolchain missing
        pass
    return {"mode": "simulate" if s.simulate else "live", "env": request.app.state.env,
            "python": platform.python_version(), "backend": __version__, "sdk": sigil.__version__,
            "sdk_adapters": adapters, "zk": zk, "database": request.app.state.engine.dialect.name,
            "registry_public_key": request.app.state.registry.public_key,
            "max_upload_bytes": s.max_upload_bytes, "monitor_interval": s.monitor_interval,
            "jobs": {"running": request.app.state.jobs.busy(), "queued": len(request.app.state.jobs.queue)}}
