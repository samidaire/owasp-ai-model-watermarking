"""SQLAlchemy 2 ORM models (DB-02). The Alembic migrations in backend/migrations create exactly these tables
(a test compares the two). ER diagram: docs/er-diagram.md.

Signed records (registrations, receipts, claims) are stored as the exact canonical JSON text that was
signed, so their signatures can be re-verified byte for byte at any time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, MetaData, String, Text,
                        TypeDecorator, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {"ix": "ix_%(table_name)s_%(column_0_name)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
          "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
          "pk": "pk_%(table_name)s"}

JSONType = JSON().with_variant(JSONB(), "postgresql")
BigId = BigInteger().with_variant(Integer(), "sqlite")    # SQLite autoincrements INTEGER PRIMARY KEY only


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite returns naive values)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


ROLES = ("owner", "verifier", "admin")


# ---------------------------------------------------------------------------------------------- accounts
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    tokens: Mapped[list["ApiToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)     # SHA-256 of the bearer token
    prefix: Mapped[str] = mapped_column(String(16))                       # first characters, for display only
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="tokens")


# ---------------------------------------------------------------------------------------------- owners and models
class Owner(Base):
    """An owner identity: an Ed25519 PUBLIC key only. Private keys and seeds never reach the server."""
    __tablename__ = "owners"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(200))
    public_key_hex: Mapped[str] = mapped_column(String(64), unique=True)
    pk_hash: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Model(Base):
    __tablename__ = "models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str] = mapped_column(String(20))                       # watermarked | suspect
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    artifacts: Mapped[list["ModelArtifact"]] = relationship(back_populates="model", cascade="all, delete-orphan")


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))                     # sanitised original name
    stored_path: Mapped[str] = mapped_column(String(500))                  # relative to the upload folder
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    framework: Mapped[str] = mapped_column(String(20))                     # pytorch | keras | onnx
    extension: Mapped[str] = mapped_column(String(10))
    layers: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    model: Mapped[Model] = relationship(back_populates="artifacts")


class WatermarkConfig(Base):
    """Public watermark parameters (sigil.protocol.Config), keyed by their Poseidon config_hash."""
    __tablename__ = "watermark_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_hash: Mapped[str] = mapped_column(String(80), unique=True)
    protocol: Mapped[int] = mapped_column(Integer)
    T: Mapped[int] = mapped_column(Integer)
    M: Mapped[int] = mapped_column(Integer)
    layer: Mapped[str] = mapped_column(String(200))
    scale_bits: Mapped[int] = mapped_column(Integer)
    w_bits: Mapped[int] = mapped_column(Integer)
    max_err: Mapped[int] = mapped_column(Integer)
    norm: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------------------------------------- registry
class Registration(Base):
    """An owner-signed sigil.registration/v2 record (CR-02), stored as the exact signed JSON."""
    __tablename__ = "registrations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"), index=True)
    watermark_config_id: Mapped[int] = mapped_column(ForeignKey("watermark_configs.id", ondelete="RESTRICT"), index=True)
    model_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("model_artifacts.id", ondelete="SET NULL"),
                                                          nullable=True, index=True)
    registration_json: Mapped[str] = mapped_column(Text)
    registration_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    commitment: Mapped[str] = mapped_column(String(80), index=True)
    model_sha256: Mapped[str] = mapped_column(String(64), index=True)
    owner_created_at: Mapped[str] = mapped_column(String(40))            # created_at as claimed by the owner
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    owner: Mapped[Owner] = relationship()
    config_row: Mapped[WatermarkConfig] = relationship()
    receipt: Mapped["Receipt | None"] = relationship(back_populates="registration", uselist=False)


class Receipt(Base):
    """The registry's signed timestamp for a registration (CR-03)."""
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="CASCADE"), unique=True)
    receipt_json: Mapped[str] = mapped_column(Text)
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    registered_at: Mapped[str] = mapped_column(String(40), index=True)
    registry_public_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    registration: Mapped[Registration] = relationship(back_populates="receipt")


class Embedding(Base):
    """An embedding report. Embedding runs where the seed lives (the owner's machine, `sigil embed`);
    the server records the public outcome only."""
    __tablename__ = "embeddings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("model_artifacts.id", ondelete="SET NULL"),
                                                          nullable=True, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id", ondelete="SET NULL"), nullable=True)
    watermark_config_id: Mapped[int | None] = mapped_column(ForeignKey("watermark_configs.id", ondelete="SET NULL"),
                                                            nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    metrics: Mapped[dict] = mapped_column(JSONType)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Claim(Base):
    """A verifier-issued sigil.claim/v2 (fresh nonce) about a suspect model file."""
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_uuid: Mapped[str] = mapped_column(String(36), unique=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id", ondelete="RESTRICT"), index=True)
    suspect_artifact_id: Mapped[int] = mapped_column(ForeignKey("model_artifacts.id", ondelete="RESTRICT"), index=True)
    claim_json: Mapped[str] = mapped_column(Text)
    nonce: Mapped[str] = mapped_column(String(80))
    opened_at: Mapped[str] = mapped_column(String(40))
    opened_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    registration: Mapped[Registration] = relationship()
    suspect: Mapped[ModelArtifact] = relationship()


class Proof(Base):
    """A proof bundle (proof.json + public.json) the owner produced with `sigil prove` for a claim."""
    __tablename__ = "proofs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    proof_json: Mapped[str] = mapped_column(Text)
    public_json: Mapped[str] = mapped_column(Text)
    proof_sha256: Mapped[str] = mapped_column(String(64))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    claim: Mapped[Claim] = relationship()


class Verification(Base):
    """A persisted verdict of sigil.verify.verify_ownership, with every named reason (ZK-06)."""
    __tablename__ = "verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proof_id: Mapped[int] = mapped_column(ForeignKey("proofs.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    accepted: Mapped[bool] = mapped_column(Boolean)
    verdict: Mapped[dict] = mapped_column(JSONType)
    reasons: Mapped[list] = mapped_column(JSONType)
    vector_source: Mapped[str] = mapped_column(String(20))               # sdk_adapter | request (TODO M4)
    suspect_sha256: Mapped[str] = mapped_column(String(64))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    proof: Mapped[Proof] = relationship()
    claim: Mapped[Claim] = relationship()


# ---------------------------------------------------------------------------------------------- robustness
class AttackRun(Base):
    __tablename__ = "attack_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(40))                       # demo-import | job
    commitment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    results_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    results: Mapped[list["AttackResult"]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                         order_by="AttackResult.id")


class AttackResult(Base):
    __tablename__ = "attack_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attack_run_id: Mapped[int] = mapped_column(ForeignKey("attack_runs.id", ondelete="CASCADE"), index=True)
    attack: Mapped[str] = mapped_column(String(200))
    family: Mapped[str] = mapped_column(String(40))
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner_ber: Mapped[float | None] = mapped_column(Float, nullable=True)
    survives: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    run: Mapped[AttackRun] = relationship(back_populates="results")


# ---------------------------------------------------------------------------------------------- monitoring
class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    environment: Mapped[str] = mapped_column(String(100))
    artifact_path: Mapped[str] = mapped_column(String(1000))
    expected_sha256: Mapped[str] = mapped_column(String(64))
    model_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("model_artifacts.id", ondelete="SET NULL"),
                                                          nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[str] = mapped_column(String(20), default="pending")   # pending | ok | mismatch | missing | error
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeploymentCheck(Base):
    __tablename__ = "deployment_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    trigger: Mapped[str] = mapped_column(String(20))                       # manual | scheduler
    status: Mapped[str] = mapped_column(String(20))                        # ok | mismatch | missing | error
    alert: Mapped[bool] = mapped_column(Boolean)
    expected_sha256: Mapped[str] = mapped_column(String(64))
    observed_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # observed hash has a registration
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------------------------- jobs
class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    step: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), default="demo")
    source: Mapped[str] = mapped_column(String(10))                        # v1 | v2
    status: Mapped[str] = mapped_column(String(20), index=True)            # queued | running | succeeded | failed |
    #                                                                         cancelled | timed_out | interrupted
    code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    tries: Mapped[int] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(300), nullable=True)   # model_test: the catalogue id
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout: Mapped[float | None] = mapped_column(Float, nullable=True)
    started: Mapped[float] = mapped_column(Float)                           # unix seconds, as in v1 JobInfo
    ended: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines: Mapped[int] = mapped_column(Integer, default=0)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobLog(Base):
    __tablename__ = "job_logs"
    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_job_logs_job_id_seq"),)
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)                               # 0-based line index (SSE id)
    line: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------------------------------------- audit
class AuditEvent(Base):
    """Append-only, hash-chained (DB-03): hash = SHA-256(prev_hash || event_json), event_json canonical.
    UPDATE and DELETE are refused by database triggers (see the migration)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    seq: Mapped[int] = mapped_column(BigInteger, unique=True)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSONType)
    event_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


# ---------------------------------------------------------------------------------------------- demo history (DB-04)
class ResultSnapshot(Base):
    """A copy of a demo/results/*.json file as it was at some point (import-demo, or after a live run)."""
    __tablename__ = "result_snapshots"
    __table_args__ = (UniqueConstraint("name", "sha256", name="uq_result_snapshots_name_sha256"),
                      Index("ix_result_snapshots_name", "name"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))                          # train, attacks, ezkl_private_owner, ...
    path: Mapped[str] = mapped_column(String(200))                         # relative to demo/results
    sha256: Mapped[str] = mapped_column(String(64))
    commitment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    content: Mapped[dict | list] = mapped_column(JSONType)
    source: Mapped[str] = mapped_column(String(40))                        # demo-import | job:<id>
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
