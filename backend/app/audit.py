"""Append-only, hash-chained audit log (DB-03).

    event_json = canonical JSON of {seq, ts, actor, action, resource_type, resource_id, details}
                 (keys sorted, no whitespace, UTF-8)
    hash       = SHA-256( prev_hash_hex (ASCII) || event_json (UTF-8) ),  prev_hash of seq 1 = 64 zeros

Every state-changing call writes one event, in the same transaction as the change: `append()` adds the
event and commits the session. Appends are serialised (a process lock, plus a transaction-scoped advisory
lock on PostgreSQL), so the chain never forks. UPDATE and DELETE on the table are refused by triggers; an
attacker who bypasses them (e.g. drops the triggers) is caught by `verify_chain()`, and rewriting the whole
chain is caught by comparing against a previously exported, registry-signed head (`verify_chain(anchor=...)`).
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditEvent

GENESIS = "0" * 64
_LOCK = threading.Lock()
_PG_LOCK_KEY = 0x5161_6175_6469_74      # pg_advisory_xact_lock key for audit appends


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def chain_hash(prev_hash: str, event_json: str) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + event_json.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def append(db: Session, actor: str, action: str, resource_type: str | None = None, resource_id=None,
           details: dict | None = None) -> AuditEvent:
    """Add one event and COMMIT the session (the change it describes is committed with it)."""
    with _LOCK:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_LOCK_KEY})
        last = db.execute(select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)).first()
        seq = (last.seq + 1) if last else 1
        prev = last.hash if last else GENESIS
        event = {"seq": seq, "ts": _now(), "actor": actor, "action": action, "resource_type": resource_type,
                 "resource_id": None if resource_id is None else str(resource_id), "details": details or {}}
        ej = canonical(event)
        row = AuditEvent(seq=seq, ts=event["ts"], actor=actor, action=action, resource_type=resource_type,
                         resource_id=event["resource_id"], details=event["details"], event_json=ej, prev_hash=prev,
                         hash=chain_hash(prev, ej))
        db.add(row)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    return row


def event_dict(row: AuditEvent) -> dict:
    return {"seq": row.seq, "ts": row.ts, "actor": row.actor, "action": row.action, "resource_type": row.resource_type,
            "resource_id": row.resource_id, "details": row.details, "event_json": row.event_json,
            "prev_hash": row.prev_hash, "hash": row.hash}


def verify_events(events, anchor: tuple[int, str] | None = None) -> dict:
    """Check a sequence of events (ORM rows or exported dicts) in seq order. Returns
    {valid, count, head_seq, head_hash, problems: [{seq, problem}], anchor_ok}."""
    prev, expected, problems, head_seq, count = GENESIS, 1, [], 0, 0
    anchor_ok = None if anchor is None else False
    for ev in events:
        d = event_dict(ev) if isinstance(ev, AuditEvent) else ev
        count += 1
        seq = d["seq"]
        if seq != expected:
            problems.append({"seq": seq, "problem": f"sequence gap or reordering (expected {expected})"})
        if d["prev_hash"] != prev:
            problems.append({"seq": seq, "problem": "prev_hash does not match the previous event's hash"})
        if chain_hash(d["prev_hash"], d["event_json"]) != d["hash"]:
            problems.append({"seq": seq, "problem": "hash does not match SHA-256(prev_hash || event_json)"})
        try:
            parsed = json.loads(d["event_json"])
            fields = ("seq", "ts", "actor", "action", "resource_type", "resource_id", "details")
            if canonical(parsed) != d["event_json"]:
                problems.append({"seq": seq, "problem": "event_json is not canonical"})
            if any(parsed.get(f) != d[f] for f in fields):
                problems.append({"seq": seq, "problem": "stored columns differ from the hashed event"})
        except (ValueError, TypeError, KeyError):
            problems.append({"seq": seq, "problem": "event_json is not valid JSON"})
        if anchor is not None and seq == anchor[0]:
            anchor_ok = d["hash"] == anchor[1]
        prev, expected, head_seq = d["hash"], seq + 1, seq
    if anchor is not None and not anchor_ok:
        problems.append({"seq": anchor[0], "problem": "the chain no longer contains the anchored head (rewritten?)"})
    return {"valid": not problems, "count": count, "head_seq": head_seq, "head_hash": prev if count else GENESIS,
            "problems": problems, "anchor_ok": anchor_ok}


def iter_events(db: Session, batch: int = 1000):
    last = 0
    while True:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.seq > last).order_by(AuditEvent.seq).limit(batch)).all()
        if not rows:
            return
        yield from rows
        last = rows[-1].seq


def verify_chain(db: Session, anchor: tuple[int, str] | None = None) -> dict:
    return verify_events(iter_events(db), anchor)


def head(db: Session) -> tuple[int, str]:
    last = db.execute(select(AuditEvent.seq, AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)).first()
    return (last.seq, last.hash) if last else (0, GENESIS)
