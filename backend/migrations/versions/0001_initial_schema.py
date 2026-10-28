"""Initial schema (DB-02) and the append-only audit log (DB-03).

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
BIGID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def TS(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def STR(name, n, nullable=False):
    return sa.Column(name, sa.String(length=n), nullable=nullable)


def INT(name, nullable=False):
    return sa.Column(name, sa.Integer(), nullable=nullable)


def fk(t, col, table, ondelete):
    return sa.ForeignKeyConstraint([col], [f"{table}.id"], name=op.f(f"fk_{t}_{col}_{table}"), ondelete=ondelete)


def pk(t):
    return sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}"))


def uq(t, col):
    return sa.UniqueConstraint(col, name=op.f(f"uq_{t}_{col}"))


def ix(t, *cols):
    for col in cols:
        op.create_index(op.f(f"ix_{t}_{col}"), t, [col], unique=False)


# Append-only audit log: refuse UPDATE / DELETE (and TRUNCATE on PostgreSQL) at the database level.
PG_AUDIT_FN = """
CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only (DB-03)';
END;
$$ LANGUAGE plpgsql
"""
PG_TRIGGERS = [
    "CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events "
    "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()",
    "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
    "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()",
]
SQLITE_TRIGGERS = [
    "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only (DB-03)'); END",
    "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only (DB-03)'); END",
]


def upgrade() -> None:
    t = "users"
    op.create_table(t, INT("id"), STR("username", 64), STR("password_hash", 255), STR("role", 16),
                    sa.Column("is_active", sa.Boolean(), nullable=False), TS("created_at"),
                    pk(t), uq(t, "username"))

    t = "api_tokens"
    op.create_table(t, INT("id"), INT("user_id"), STR("name", 100), STR("token_hash", 64), STR("prefix", 16),
                    TS("created_at"), TS("last_used_at", True), TS("expires_at", True), TS("revoked_at", True),
                    fk(t, "user_id", "users", "CASCADE"), pk(t), uq(t, "token_hash"))
    ix(t, "user_id")

    t = "owners"
    op.create_table(t, INT("id"), INT("user_id", True), STR("label", 200), STR("public_key_hex", 64), STR("pk_hash", 80),
                    TS("created_at"), fk(t, "user_id", "users", "SET NULL"), pk(t), uq(t, "public_key_hex"))
    ix(t, "pk_hash", "user_id")

    t = "models"
    op.create_table(t, INT("id"), STR("name", 200), sa.Column("description", sa.Text(), nullable=True),
                    STR("purpose", 20), INT("created_by", True), TS("created_at"),
                    fk(t, "created_by", "users", "SET NULL"), pk(t))

    t = "model_artifacts"
    op.create_table(t, INT("id"), INT("model_id"), STR("filename", 255), STR("stored_path", 500), STR("sha256", 64),
                    sa.Column("size_bytes", sa.BigInteger(), nullable=False), STR("framework", 20), STR("extension", 10),
                    sa.Column("layers", JSON, nullable=True), INT("uploaded_by", True), TS("created_at"),
                    fk(t, "model_id", "models", "CASCADE"), fk(t, "uploaded_by", "users", "SET NULL"), pk(t))
    ix(t, "model_id", "sha256")

    t = "watermark_configs"
    op.create_table(t, INT("id"), STR("config_hash", 80), INT("protocol"), INT("T"), INT("M"), STR("layer", 200),
                    INT("scale_bits"), INT("w_bits"), INT("max_err"), STR("norm", 20),
                    sa.Column("config", JSON, nullable=False), TS("created_at"), pk(t), uq(t, "config_hash"))

    t = "jobs"
    op.create_table(t, STR("id", 32), STR("step", 40), STR("kind", 20), STR("source", 10), STR("status", 20),
                    INT("code", True), sa.Column("simulated", sa.Boolean(), nullable=False), INT("tries"),
                    sa.Column("cancelled", sa.Boolean(), nullable=False),
                    sa.Column("timed_out", sa.Boolean(), nullable=False),
                    sa.Column("timeout", sa.Float(), nullable=True), sa.Column("started", sa.Float(), nullable=False),
                    sa.Column("ended", sa.Float(), nullable=True), INT("lines"), INT("submitted_by", True),
                    TS("created_at"), fk(t, "submitted_by", "users", "SET NULL"), pk(t))
    ix(t, "status")

    t = "job_logs"
    op.create_table(t, sa.Column("id", BIGID, autoincrement=True, nullable=False), STR("job_id", 32), INT("seq"),
                    sa.Column("line", sa.Text(), nullable=False), fk(t, "job_id", "jobs", "CASCADE"), pk(t),
                    sa.UniqueConstraint("job_id", "seq", name="uq_job_logs_job_id_seq"))

    t = "registrations"
    op.create_table(t, INT("id"), INT("owner_id"), INT("watermark_config_id"), INT("model_artifact_id", True),
                    sa.Column("registration_json", sa.Text(), nullable=False), STR("registration_sha256", 64),
                    STR("commitment", 80), STR("model_sha256", 64), STR("owner_created_at", 40),
                    INT("submitted_by", True), TS("created_at"),
                    fk(t, "model_artifact_id", "model_artifacts", "SET NULL"), fk(t, "owner_id", "owners", "RESTRICT"),
                    fk(t, "submitted_by", "users", "SET NULL"),
                    fk(t, "watermark_config_id", "watermark_configs", "RESTRICT"), pk(t), uq(t, "registration_sha256"))
    ix(t, "commitment", "model_artifact_id", "model_sha256", "owner_id", "watermark_config_id")

    t = "receipts"
    op.create_table(t, INT("id"), INT("registration_id"), sa.Column("receipt_json", sa.Text(), nullable=False),
                    STR("receipt_sha256", 64), STR("registered_at", 40), STR("registry_public_key", 64), TS("created_at"),
                    fk(t, "registration_id", "registrations", "CASCADE"), pk(t), uq(t, "registration_id"))
    ix(t, "registered_at")

    t = "embeddings"
    op.create_table(t, INT("id"), INT("model_artifact_id", True), INT("owner_id", True), INT("watermark_config_id", True),
                    STR("job_id", 32, True), STR("status", 20), sa.Column("metrics", JSON, nullable=False),
                    INT("created_by", True), TS("created_at"),
                    fk(t, "created_by", "users", "SET NULL"), fk(t, "job_id", "jobs", "SET NULL"),
                    fk(t, "model_artifact_id", "model_artifacts", "SET NULL"), fk(t, "owner_id", "owners", "SET NULL"),
                    fk(t, "watermark_config_id", "watermark_configs", "SET NULL"), pk(t))
    ix(t, "model_artifact_id")

    t = "claims"
    op.create_table(t, INT("id"), STR("claim_uuid", 36), INT("registration_id"), INT("suspect_artifact_id"),
                    sa.Column("claim_json", sa.Text(), nullable=False), STR("nonce", 80), STR("opened_at", 40),
                    INT("opened_by", True), TS("created_at"),
                    fk(t, "opened_by", "users", "SET NULL"), fk(t, "registration_id", "registrations", "RESTRICT"),
                    fk(t, "suspect_artifact_id", "model_artifacts", "RESTRICT"), pk(t), uq(t, "claim_uuid"))
    ix(t, "registration_id", "suspect_artifact_id")

    t = "proofs"
    op.create_table(t, INT("id"), INT("claim_id"), sa.Column("proof_json", sa.Text(), nullable=False),
                    sa.Column("public_json", sa.Text(), nullable=False), STR("proof_sha256", 64),
                    INT("submitted_by", True), TS("created_at"),
                    fk(t, "claim_id", "claims", "CASCADE"), fk(t, "submitted_by", "users", "SET NULL"), pk(t))
    ix(t, "claim_id")

    t = "verifications"
    op.create_table(t, INT("id"), INT("proof_id"), INT("claim_id"), sa.Column("accepted", sa.Boolean(), nullable=False),
                    sa.Column("verdict", JSON, nullable=False), sa.Column("reasons", JSON, nullable=False),
                    STR("vector_source", 20), STR("suspect_sha256", 64), INT("verified_by", True), TS("created_at"),
                    fk(t, "claim_id", "claims", "CASCADE"), fk(t, "proof_id", "proofs", "CASCADE"),
                    fk(t, "verified_by", "users", "SET NULL"), pk(t))
    ix(t, "claim_id", "proof_id")

    t = "attack_runs"
    op.create_table(t, INT("id"), STR("job_id", 32, True), STR("source", 40), STR("commitment", 80, True),
                    sa.Column("threshold", sa.Float(), nullable=True), sa.Column("simulated", sa.Boolean(), nullable=False),
                    STR("results_sha256", 64, True), TS("created_at"), fk(t, "job_id", "jobs", "SET NULL"), pk(t))
    ix(t, "job_id", "results_sha256")

    t = "attack_results"
    op.create_table(t, INT("id"), INT("attack_run_id"), STR("attack", 200), STR("family", 40),
                    sa.Column("accuracy", sa.Float(), nullable=True), sa.Column("owner_ber", sa.Float(), nullable=True),
                    sa.Column("survives", sa.Boolean(), nullable=True),
                    fk(t, "attack_run_id", "attack_runs", "CASCADE"), pk(t))
    ix(t, "attack_run_id")

    t = "deployments"
    op.create_table(t, INT("id"), STR("name", 200), STR("environment", 100), STR("artifact_path", 1000),
                    STR("expected_sha256", 64), INT("model_artifact_id", True),
                    sa.Column("active", sa.Boolean(), nullable=False), STR("last_status", 20), TS("last_checked_at", True),
                    INT("created_by", True), TS("created_at"),
                    fk(t, "created_by", "users", "SET NULL"), fk(t, "model_artifact_id", "model_artifacts", "SET NULL"),
                    pk(t))

    t = "deployment_checks"
    op.create_table(t, INT("id"), INT("deployment_id"), TS("checked_at"), STR("trigger", 20), STR("status", 20),
                    sa.Column("alert", sa.Boolean(), nullable=False), STR("expected_sha256", 64),
                    STR("observed_sha256", 64, True), sa.Column("registered", sa.Boolean(), nullable=True),
                    sa.Column("detail", sa.Text(), nullable=True),
                    fk(t, "deployment_id", "deployments", "CASCADE"), pk(t))
    ix(t, "deployment_id")

    t = "audit_events"
    op.create_table(t, sa.Column("id", BIGID, autoincrement=True, nullable=False),
                    sa.Column("seq", sa.BigInteger(), nullable=False), STR("ts", 40), STR("actor", 120), STR("action", 80),
                    STR("resource_type", 40, True), STR("resource_id", 80, True),
                    sa.Column("details", JSON, nullable=False), sa.Column("event_json", sa.Text(), nullable=False),
                    STR("prev_hash", 64), STR("hash", 64), pk(t), uq(t, "hash"), uq(t, "seq"))
    ix(t, "action")

    t = "result_snapshots"
    op.create_table(t, INT("id"), STR("name", 80), STR("path", 200), STR("sha256", 64), STR("commitment", 80, True),
                    sa.Column("content", JSON, nullable=False), STR("source", 40), TS("imported_at"), pk(t),
                    sa.UniqueConstraint("name", "sha256", name="uq_result_snapshots_name_sha256"))
    op.create_index("ix_result_snapshots_name", t, ["name"], unique=False)

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(PG_AUDIT_FN)
        for stmt in PG_TRIGGERS:
            op.execute(stmt)
    elif dialect == "sqlite":
        for stmt in SQLITE_TRIGGERS:
            op.execute(stmt)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    for t in ("result_snapshots", "audit_events", "deployment_checks", "deployments", "attack_results", "attack_runs",
              "verifications", "proofs", "claims", "embeddings", "receipts", "registrations", "job_logs", "jobs",
              "watermark_configs", "model_artifacts", "models", "owners", "api_tokens", "users"):
        op.drop_table(t)
