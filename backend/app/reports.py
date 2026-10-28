"""Reports (API-08), generated from database records and signed by the registry key.

  * Ownership certificate per verification: signed JSON (sigil.certificate/v1) and a PDF rendering of it.
  * Audit export (JSON or CSV) with the hash-chain proof: every event's event_json, prev_hash and hash, the chain
    status, and a registry-signed head (seq, hash).
  * Compliance report (JSON + PDF): the evidence in the database mapped to the OWASP AI Exchange
    #MODEL WATERMARKING text (quoted from 01_Literature_Gap_Analysis.md §2) and to REQUIREMENTS.md IDs.
PDFs use only the core PDF fonts (no downloads), so they render offline.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import __version__, audit
from .models import (AttackRun, Claim, Deployment, Proof, Receipt, Registration, ResultSnapshot,
                     Verification)
from .registry import Registry, no_floats

CERT_SCHEMA = "sigil.certificate/v1"
AUDIT_EXPORT_SCHEMA = "sigil.audit-export/v1"
AUDIT_HEAD_SCHEMA = "sigil.audit-head/v1"
COMPLIANCE_SCHEMA = "sigil.compliance-report/v1"

# Project statements that must stay true wherever results are shown (REQUIREMENTS.md §15).
STATEMENTS = [
    "theta is indicative until the null-model calibration (WM-07) is done.",
    "Groth16 relies on a trusted setup: a public Powers of Tau file plus our own phase-2 contribution.",
    "White-box marks do not survive model extraction; only the trigger-set mark is evaluated for that (OWASP L1).",
    "The registry timestamp, not the watermark, decides between two valid marks (overwriting).",
]

# OWASP AI Exchange #MODEL WATERMARKING, verbatim as quoted in 01_Literature_Gap_Analysis.md §2 [S4].
# The labels R1-R3 and L1 are this project's, not OWASP's.
OWASP_SOURCE = ("OWASP AI Exchange, #MODEL WATERMARKING (owaspai.org/go/modelwatermarking; PDF export generated "
                "2026-10-03, pp. 230-231), as quoted in 01_Literature_Gap_Analysis.md section 2. The labels R1-R3 "
                "and L1 are this project's, not OWASP's.")
OWASP_TEXT = {
    "R1": ("Robustness", "Watermarking techniques should be designed to remain detectable even if the model is "
                         "modified (for example through fine-tuning or pruning)"),
    "R2": ("Non-ambiguity", "...and to avoid ambiguity where multiple parties could plausibly claim ownership of "
                            "the same model."),
    "R3": ("Purpose", "used to demonstrate ownership after a model has been stolen or replicated, rather than to "
                      "prevent the theft itself"),
    "L1": ("Limitation", "Watermarking can be effective evidence for direct model theft, but is limited for model "
                         "exfiltration ... typical watermark approached are represented in data that would not be in "
                         "distribution"),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------- certificate
def certificate(db: Session, registry: Registry, v: Verification) -> dict:
    claim: Claim = v.claim
    reg: Registration = claim.registration
    rec = json.loads(reg.registration_json)
    rcp = json.loads(reg.receipt.receipt_json) if reg.receipt else None
    proof: Proof = v.proof
    doc = {
        "schema": CERT_SCHEMA,
        "verification_id": v.id,
        "verified_at": v.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "ACCEPTED" if v.accepted else "REJECTED",
        "accepted": v.accepted,
        "reasons": list(v.reasons),
        "checks": {k: bool(x) for k, x in (v.verdict or {}).get("checks", {}).items()},
        "suspect_vector_source": v.vector_source,
        "suspect_model_sha256": v.suspect_sha256,
        "registration": rec,
        "registration_sha256": reg.registration_sha256,
        "receipt": rcp,
        "claim": json.loads(claim.claim_json),
        "proof_sha256": proof.proof_sha256,
        "public_signals": [str(x) for x in json.loads(proof.public_json)],
        "statements": STATEMENTS + ([
            "TODO(M4): the suspect's Uchida vector was supplied with the request, not recomputed from the file "
            "by the SDK adapters."] if v.vector_source == "request" else []),
        "generator": f"sigil backend {__version__}",
    }
    return registry.sign_document(no_floats(doc))


# ---------------------------------------------------------------------------------------------- audit export
def audit_head(db: Session, registry: Registry) -> dict:
    seq, h = audit.head(db)
    return registry.sign_document({"schema": AUDIT_HEAD_SCHEMA, "head_seq": seq, "head_hash": h})


def audit_export_json(db: Session, registry: Registry) -> dict:
    events = [audit.event_dict(e) for e in audit.iter_events(db)]
    status = audit.verify_events(events)
    doc = {"schema": AUDIT_EXPORT_SCHEMA, "exported_at": _now(),
           "hash_rule": "hash = SHA-256(prev_hash_hex || event_json); prev_hash of seq 1 = 64 zeros",
           "chain": {k: status[k] for k in ("valid", "count", "head_seq", "head_hash")},
           "chain_problems": status["problems"], "events": events}
    return registry.sign_document(no_floats(doc))


AUDIT_CSV_COLUMNS = ["seq", "ts", "actor", "action", "resource_type", "resource_id", "details", "event_json",
                     "prev_hash", "hash"]


def audit_export_csv(db: Session, registry: Registry) -> tuple[str, dict]:
    """CSV text plus the signed head (sent as headers) that anchors it."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(AUDIT_CSV_COLUMNS)
    events = []
    for e in audit.iter_events(db):
        d = audit.event_dict(e)
        events.append(d)
        w.writerow([d["seq"], d["ts"], d["actor"], d["action"], d["resource_type"] or "", d["resource_id"] or "",
                    json.dumps(d["details"], sort_keys=True), d["event_json"], d["prev_hash"], d["hash"]])
    status = audit.verify_events(events)
    head = registry.sign_document({"schema": AUDIT_HEAD_SCHEMA, "head_seq": status["head_seq"],
                                   "head_hash": status["head_hash"], "chain_valid": status["valid"],
                                   "count": status["count"]})
    return buf.getvalue(), head


def verify_audit_csv(text: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(text)))
    events = [{"seq": int(r["seq"]), "ts": r["ts"], "actor": r["actor"], "action": r["action"],
               "resource_type": r["resource_type"] or None, "resource_id": r["resource_id"] or None,
               "details": json.loads(r["details"]), "event_json": r["event_json"], "prev_hash": r["prev_hash"],
               "hash": r["hash"]} for r in rows]
    return audit.verify_events(events)


# ---------------------------------------------------------------------------------------------- compliance
def _count(db, model, *where) -> int:
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    return int(db.scalar(q) or 0)


def compliance(db: Session, registry: Registry) -> dict:
    from sigil.records import verify_registration

    regs = db.scalars(select(Registration)).all()
    valid_regs = sum(1 for r in regs if not verify_registration(json.loads(r.registration_json)))
    receipts = _count(db, Receipt)
    ver_total = _count(db, Verification)
    ver_ok = _count(db, Verification, Verification.accepted.is_(True))
    ver_request = _count(db, Verification, Verification.vector_source == "request")
    last_run = db.scalars(select(AttackRun).order_by(AttackRun.id.desc()).limit(1)).first()
    chain = audit.verify_chain(db)
    deps = _count(db, Deployment, Deployment.active.is_(True))
    alerts = _count(db, Deployment, Deployment.active.is_(True), Deployment.last_status.in_(("mismatch", "missing", "error")))
    cs = db.scalars(select(ResultSnapshot).where(ResultSnapshot.name == "committed_seed")
                    .order_by(ResultSnapshot.id.desc()).limit(1)).first()
    forg = db.scalars(select(ResultSnapshot).where(ResultSnapshot.name == "forgery")
                      .order_by(ResultSnapshot.id.desc()).limit(1)).first()

    def status(ok: bool, partial: bool = False) -> str:
        return "evidence" if ok else ("partial" if partial else "missing")

    attacks = None
    if last_run is not None:
        failing = [r.attack for r in last_run.results if r.survives is False]
        attacks = {"run_id": last_run.id, "source": last_run.source, "simulated": last_run.simulated,
                   "attacks": len(last_run.results), "survived": sum(1 for r in last_run.results if r.survives),
                   "removed_by": failing}
    d2 = (cs.content or {}).get("d2") if cs is not None and isinstance(cs.content, dict) else None
    items = [
        {"id": "R1", "label": OWASP_TEXT["R1"][0], "owasp_text": OWASP_TEXT["R1"][1],
         "requirements": ["ROB-01", "ROB-04", "ROB-05", "WM-01", "FIX-16"],
         "status": status(attacks is not None and attacks["attacks"] > 0, False),
         "evidence": {"latest_attack_run": attacks},
         "notes": "Robustness is measured, not assumed: attacks that remove the mark are listed, not hidden. "
                  "Multi-seed statistics are ROB-04."},
        {"id": "R2", "label": OWASP_TEXT["R2"][0], "owasp_text": OWASP_TEXT["R2"][1],
         "requirements": ["CR-01", "CR-02", "CR-03", "CR-06", "FIX-04", "FIX-05", "ZK-06"],
         "status": status(receipts > 0 and valid_regs == len(regs), cs is not None or forg is not None),
         "evidence": {"registrations": len(regs), "registrations_valid": valid_regs, "registry_receipts": receipts,
                      "registry_public_key": registry.public_key,
                      "dispute_rule": "earliest valid registry receipt wins (CR-03)",
                      "committed_seed_d2": {k: d2.get(k) for k in ("accepted", "tries", "log2_work", "log2_work_T256")}
                      if isinstance(d2, dict) else None,
                      "forgery_demo_snapshot": forg.sha256 if forg is not None else None},
         "notes": "Owner-signed registrations (Ed25519) bind the seed commitment, config and model hash; the "
                  "registry's signed timestamp decides disputes."},
        {"id": "R3", "label": OWASP_TEXT["R3"][0], "owasp_text": OWASP_TEXT["R3"][1],
         "requirements": ["ZK-01", "ZK-05", "ZK-06", "ZK-07", "API-08"],
         "status": status(ver_ok > 0 and ver_request < ver_total, ver_total > 0),
         "evidence": {"verifications": ver_total, "accepted": ver_ok, "rejected": ver_total - ver_ok,
                      "vector_supplied_by_request": ver_request,
                      "claims": _count(db, Claim), "proofs": _count(db, Proof)},
         "notes": "Ownership is shown after the fact with a zero-knowledge proof bound to a verifier-issued claim "
                  "nonce; every rejection carries a named reason."},
        {"id": "L1", "label": OWASP_TEXT["L1"][0], "owasp_text": OWASP_TEXT["L1"][1],
         "requirements": ["WM-06", "ROB-03"], "status": "missing",
         "evidence": {"trigger_set_evaluation": None},
         "notes": "White-box marks do not survive model extraction. The committed trigger-set mark (WM-06) and the "
                  "extraction study (ROB-03) are not in this backend's records yet."},
    ]
    controls = [
        {"id": "DB-03", "title": "Append-only hash-chained audit log",
         "status": status(chain["valid"]), "evidence": {k: chain[k] for k in ("valid", "count", "head_seq", "head_hash")}},
        {"id": "API-09", "title": "Deployment monitoring", "status": status(deps > 0),
         "evidence": {"active_deployments": deps, "open_alerts": alerts}},
        {"id": "CR-04", "title": "No secrets on the server", "status": "evidence",
         "evidence": {"stored": "owner public keys, signed public records, proofs; never seeds or private keys"}},
    ]
    doc = {"schema": COMPLIANCE_SCHEMA, "generated_at": _now(), "source": OWASP_SOURCE, "items": items,
           "controls": controls, "statements": STATEMENTS, "generator": f"sigil backend {__version__}"}
    return registry.sign_document(no_floats(doc))


# ---------------------------------------------------------------------------------------------- PDF rendering
def _pdf(title: str, sections: list[tuple[str, list]]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    mono = styles["Code"].clone("mono", fontSize=7, leading=8.5)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=title, author="Sigil backend", invariant=1)
    story = [Paragraph(escape(title), styles["Title"])]

    def para(text, style=small):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    for heading, rows in sections:
        story.append(Paragraph(escape(heading), styles["Heading2"]))
        for row in rows:
            if isinstance(row, tuple):
                t = Table([[para(row[0]), para(row[1], mono if row[1] and len(str(row[1])) > 40 else small)]],
                          colWidths=[48 * mm, 130 * mm])
                t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
                story.append(t)
            else:
                story.append(para(row))
        story.append(Spacer(1, 4 * mm))
    doc.build(story)
    return buf.getvalue()


def _ascii(text) -> str:
    """Core PDF fonts are Latin-1 only."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _clean(rows) -> list:
    return [(_ascii(r[0]), _ascii(r[1])) if isinstance(r, tuple) else _ascii(r) for r in rows]


def certificate_pdf(cert: dict) -> bytes:
    rec, rcp, claim = cert["registration"], cert.get("receipt") or {}, cert["claim"]
    cfg = rec.get("config", {})
    sections = [
        ("Verdict", [("Result", cert["verdict"]), ("Verification", f"#{cert['verification_id']} at {cert['verified_at']}"),
                     *[("Reason", r) for r in cert["reasons"]],
                     *[(f"check: {k}", "pass" if v else "FAIL") for k, v in cert["checks"].items()]]),
        ("Registration (owner-signed)", [("Owner public key", rec.get("owner_public_key")), ("pk_hash", rec.get("pk_hash")),
                                         ("Commitment", rec.get("commitment")), ("Model SHA-256", rec.get("model_sha256")),
                                         ("Config", f"T={cfg.get('T')} M={cfg.get('M')} layer={cfg.get('layer')} "
                                                    f"max_err={cfg.get('max_err')} (theta = max_err/T)"),
                                         ("Created (owner)", rec.get("created_at")),
                                         ("Registration SHA-256", cert["registration_sha256"])]),
        ("Registry receipt (timestamp)", [("Registered at", rcp.get("registered_at")),
                                          ("Registry key", rcp.get("registry_public_key"))]),
        ("Claim (verifier-issued)", [("Claim id", claim.get("claim_id")), ("Nonce", claim.get("nonce")),
                                     ("Opened at", claim.get("opened_at")),
                                     ("Suspect SHA-256", cert["suspect_model_sha256"]),
                                     ("Suspect vector", cert["suspect_vector_source"])]),
        ("Proof", [("Proof SHA-256", cert["proof_sha256"]), *[(f"public[{i}]", s) for i, s in enumerate(cert["public_signals"])]]),
        ("Statements", list(cert["statements"])),
        ("Signature", [("Registry public key", cert["registry_public_key"]), ("Signed at", cert["signed_at"]),
                       ("Ed25519 signature", cert["registry_signature"]),
                       "Verify the signed JSON (GET .../certificate) against the registry public key; this PDF is a "
                       "rendering of it."]),
    ]
    return _pdf("Sigil ownership verification certificate", [(h, _clean(rows)) for h, rows in sections])


def compliance_pdf(rep: dict) -> bytes:
    sections = [("Source", [_ascii(rep["source"])])]
    for it in rep["items"]:
        rows = [("OWASP text", it["owasp_text"]), ("Requirements", ", ".join(it["requirements"])),
                ("Status", it["status"]), ("Evidence", json.dumps(it["evidence"], indent=1)), ("Notes", it["notes"])]
        sections.append((f"{it['id']} {it['label']}", [(_ascii(a), _ascii(b)) for a, b in rows]))
    sections.append(("Controls", [(_ascii(f"{c['id']} {c['title']}"), _ascii(f"{c['status']}: {json.dumps(c['evidence'])}"))
                                  for c in rep["controls"]]))
    sections.append(("Statements", [_ascii(s) for s in rep["statements"]]))
    sections.append(("Signature", [("Registry public key", rep["registry_public_key"]), ("Signed at", rep["signed_at"]),
                                   ("Ed25519 signature", rep["registry_signature"])]))
    return _pdf("Sigil compliance report: OWASP AI Exchange #MODEL WATERMARKING", sections)
