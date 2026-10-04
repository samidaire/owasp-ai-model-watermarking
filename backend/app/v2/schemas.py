"""Request and response models of the v2 API (OpenAPI: contract/openapi.json)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["owner", "verifier", "admin"]
Hex64 = Field(pattern=r"^[0-9a-fA-F]{64}$")


class Strict(BaseModel):
    """Unknown fields are rejected, so e.g. a private key or seed sent by mistake is never accepted."""
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------------------------- auth
class LoginRequest(Strict):
    username: str
    password: str
    token_name: str = Field(default="login", max_length=100)


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    token: str = Field(description="The bearer token. Shown once; only its SHA-256 is stored.")
    token_id: int
    expires_at: datetime | None
    user: UserOut


class TokenCreate(Strict):
    name: str = Field(max_length=100)
    ttl_days: int | None = Field(default=None, ge=1, le=3650, description="default: SIGIL_TOKEN_TTL_DAYS")


class TokenInfo(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class UserCreate(Strict):
    username: str
    password: str
    role: Role


class UserUpdate(Strict):
    role: Role | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------------------------- owners
class OwnerCreate(Strict):
    public_key: str = Field(pattern=r"^[0-9a-fA-F]{64}$", description="Ed25519 public key, 32 bytes as hex")
    label: str = Field(min_length=1, max_length=200)


class OwnerOut(BaseModel):
    id: int
    label: str
    public_key: str
    pk_hash: str = Field(description="Poseidon hash of the key (protocol v2), a decimal field element")
    user_id: int | None
    created_at: datetime


# ---------------------------------------------------------------------------------------------- models
class ArtifactOut(BaseModel):
    id: int
    model_id: int
    filename: str
    sha256: str
    size_bytes: int
    framework: Literal["pytorch", "keras", "onnx"]
    extension: str
    created_at: datetime


class ModelOut(BaseModel):
    id: int
    name: str
    description: str | None
    purpose: Literal["watermarked", "suspect"]
    created_by: int | None
    created_at: datetime
    artifacts: list[ArtifactOut]


class LayersOut(BaseModel):
    artifact_id: int
    framework: str
    layers: list[dict] | None = Field(description="null when no safe loader for the format is installed")


# ---------------------------------------------------------------------------------------------- registry
class RegistrationRecord(Strict):
    """A sigil.registration/v2 record exactly as written by `sigil register` (owner-signed, canonical JSON)."""
    schema_: str = Field(alias="schema", serialization_alias="schema", max_length=64)
    owner_public_key: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    pk_hash: str = Field(max_length=80)
    config: dict[str, Any]
    config_hash: str = Field(max_length=80)
    commitment: str = Field(max_length=80)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str = Field(max_length=40)
    owner_signature: str = Field(max_length=200)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegistrationOut(BaseModel):
    id: int
    owner_id: int
    model_artifact_id: int | None
    registration_sha256: str
    commitment: str
    model_sha256: str
    config_hash: str
    owner_created_at: str
    registered_at: str | None
    registration: dict
    receipt: dict | None
    created_at: datetime


class RegistryInfo(BaseModel):
    registry_public_key: str
    trusted_registry_keys: list[str]
    receipt_schema: str
    dispute_rule: str


class EarliestOut(BaseModel):
    model_sha256: str
    candidates: int
    winner: RegistrationOut | None


# ---------------------------------------------------------------------------------------------- claims, proofs
class ClaimCreate(Strict):
    registration_id: int
    suspect_artifact_id: int = Field(description="a model artifact uploaded with purpose=suspect")


class ClaimOut(BaseModel):
    id: int
    claim_id: str
    registration_id: int
    suspect_artifact_id: int
    nonce: str
    opened_at: str
    claim: dict
    created_at: datetime


class ProofCreate(Strict):
    proof: dict[str, Any] = Field(description="proof.json from `sigil prove` (Groth16)")
    public: list[str | int] = Field(description="public.json: [pk_hash, config_hash, commitment, w_hash, nonce]")


class ProofOut(BaseModel):
    id: int
    claim_id: int
    proof_sha256: str
    public: list[str]
    created_at: datetime


# ---------------------------------------------------------------------------------------------- verifications
class VerificationCreate(Strict):
    proof_id: int
    suspect_vector: list[float] | None = Field(
        default=None, description="TODO(M4): only used while sigil.adapters is not installed. The suspect's "
                                  "Uchida vector (length M); with the adapters the server computes it from the file.")


class VerificationOut(BaseModel):
    id: int
    proof_id: int
    claim_id: int
    accepted: bool
    reasons: list[str]
    checks: dict[str, bool]
    vector_source: Literal["sdk_adapter", "request"]
    suspect_sha256: str
    created_at: datetime


# ---------------------------------------------------------------------------------------------- embeddings
class EmbeddingCreate(Strict):
    model_artifact_id: int
    owner_id: int
    config: dict[str, Any] = Field(description="sigil.protocol.Config.to_dict() (public parameters only)")
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict,
                                                         description="e.g. accuracy_before, accuracy_after, owner_ber")


class EmbeddingOut(BaseModel):
    id: int
    model_artifact_id: int | None
    owner_id: int | None
    config_hash: str | None
    status: str
    metrics: dict
    created_at: datetime


# ---------------------------------------------------------------------------------------------- jobs, attacks
class JobOut(BaseModel):
    id: str
    step: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out", "interrupted"]
    code: int | None
    simulated: bool
    tries: int
    cancelled: bool
    timed_out: bool
    timeout: float | None
    started: float
    ended: float | None
    lines: int
    source: str
    output: list[str] | None = None


class AttackJobCreate(Strict):
    step: Literal["attacks"] = "attacks"


class AttackResultOut(BaseModel):
    attack: str
    family: str
    accuracy: float | None
    owner_ber: float | None
    survives: bool | None


class AttackRunOut(BaseModel):
    id: int
    job_id: str | None
    source: str
    commitment: str | None
    threshold: float | None
    simulated: bool
    results_sha256: str | None
    created_at: datetime
    total: int
    survived: int
    results: list[AttackResultOut] | None = None


# ---------------------------------------------------------------------------------------------- deployments
class DeploymentCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=100)
    artifact_path: str = Field(min_length=1, max_length=1000,
                               description="absolute path inside one of SIGIL_DEPLOYMENT_ROOTS")
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$",
                                        description="default: the SHA-256 of model_artifact_id")
    model_artifact_id: int | None = None


class DeploymentUpdate(Strict):
    active: bool | None = None
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class DeploymentCheckOut(BaseModel):
    id: int
    deployment_id: int
    checked_at: datetime
    trigger: str
    status: Literal["ok", "mismatch", "missing", "error"]
    alert: bool
    expected_sha256: str
    observed_sha256: str | None
    registered: bool | None
    detail: str | None


class DeploymentOut(BaseModel):
    id: int
    name: str
    environment: str
    artifact_path: str
    expected_sha256: str
    model_artifact_id: int | None
    active: bool
    last_status: str
    last_checked_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------------------------- audit, reports
class AuditEventOut(BaseModel):
    seq: int
    ts: str
    actor: str
    action: str
    resource_type: str | None
    resource_id: str | None
    details: dict
    event_json: str
    prev_hash: str
    hash: str


class ChainProblem(BaseModel):
    seq: int
    problem: str


class ChainStatus(BaseModel):
    valid: bool
    count: int
    head_seq: int
    head_hash: str
    problems: list[ChainProblem]
    anchor_ok: bool | None


class SignedDocument(BaseModel):
    """Any registry-signed document (certificate, compliance report, audit export, audit head)."""
    model_config = ConfigDict(extra="allow")
    schema_: str = Field(alias="schema")
    registry_public_key: str
    signed_at: str
    registry_signature: str


class SignatureCheck(BaseModel):
    valid: bool
    problems: list[str]


class SignatureCheckRequest(Strict):
    document: dict[str, Any]


# ---------------------------------------------------------------------------------------------- system
class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str
    api_version: int = 2


class SnapshotOut(BaseModel):
    id: int
    name: str
    path: str
    sha256: str
    commitment: str | None
    source: str
    imported_at: datetime
    content: Any | None = None
