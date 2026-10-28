# Database schema (DB-02)

PostgreSQL 16 (SQLite for tests). Source of truth: `backend/app/models.py`; created by the Alembic migration
`backend/migrations/versions/0001_initial_schema.py` (a test checks the two agree). Timestamps are UTC.

```mermaid
erDiagram
    users ||--o{ api_tokens : "has"
    users ||--o{ owners : "registered"
    users ||--o{ models : "created"
    users ||--o{ jobs : "submitted"
    owners ||--o{ registrations : "signs"
    watermark_configs ||--o{ registrations : "config_hash"
    models ||--|{ model_artifacts : "files"
    model_artifacts |o--o{ registrations : "model_sha256"
    registrations ||--o| receipts : "registry timestamp"
    registrations ||--o{ claims : "about"
    model_artifacts ||--o{ claims : "suspect"
    claims ||--o{ proofs : "bundles"
    proofs ||--o{ verifications : "verdicts"
    claims ||--o{ verifications : "verified"
    model_artifacts |o--o{ embeddings : "reported for"
    owners |o--o{ embeddings : "by"
    watermark_configs |o--o{ embeddings : "with"
    jobs |o--o{ embeddings : "from"
    jobs ||--o{ job_logs : "lines"
    jobs |o--o{ attack_runs : "produced"
    attack_runs ||--|{ attack_results : "rows"
    model_artifacts |o--o{ deployments : "expected hash"
    deployments ||--o{ deployment_checks : "history"

    users {
        int id PK
        string username UK
        string password_hash "Argon2id"
        string role "owner | verifier | admin"
        bool is_active
        timestamptz created_at
    }
    api_tokens {
        int id PK
        int user_id FK
        string name
        string token_hash UK "SHA-256 of the bearer token"
        string prefix
        timestamptz expires_at
        timestamptz revoked_at
        timestamptz last_used_at
    }
    owners {
        int id PK
        int user_id FK
        string label
        string public_key_hex UK "Ed25519 public key only"
        string pk_hash "Poseidon, decimal"
    }
    models {
        int id PK
        string name
        string purpose "watermarked | suspect"
        int created_by FK
    }
    model_artifacts {
        int id PK
        int model_id FK
        string filename
        string stored_path "content-addressed, outside static roots"
        string sha256
        bigint size_bytes
        string framework "pytorch | keras | onnx"
        json layers "cached, safe loaders"
    }
    watermark_configs {
        int id PK
        string config_hash UK
        int T
        int M
        string layer
        int max_err
        json config
    }
    registrations {
        int id PK
        int owner_id FK
        int watermark_config_id FK
        int model_artifact_id FK
        text registration_json "exact owner-signed canonical JSON"
        string registration_sha256 UK
        string commitment
        string model_sha256
        string owner_created_at
    }
    receipts {
        int id PK
        int registration_id FK, UK
        text receipt_json "registry-signed"
        string registered_at
        string registry_public_key
    }
    claims {
        int id PK
        string claim_uuid UK
        int registration_id FK
        int suspect_artifact_id FK
        text claim_json
        string nonce
        string opened_at
    }
    proofs {
        int id PK
        int claim_id FK
        text proof_json
        text public_json
        string proof_sha256
    }
    verifications {
        int id PK
        int proof_id FK
        int claim_id FK
        bool accepted
        json verdict "checks, notes"
        json reasons
        string vector_source "sdk_adapter | request"
        string suspect_sha256
    }
    embeddings {
        int id PK
        int model_artifact_id FK
        int owner_id FK
        int watermark_config_id FK
        string job_id FK
        string status
        json metrics
    }
    jobs {
        string id PK
        string step
        string source "v1 | v2"
        string status "queued running succeeded failed cancelled timed_out interrupted"
        int code
        bool simulated
        string model "model_test: catalogue id"
        bool cancelled
        bool timed_out
        float started
        float ended
        int lines
    }
    job_logs {
        bigint id PK
        string job_id FK
        int seq "SSE id"
        text line
    }
    attack_runs {
        int id PK
        string job_id FK
        string source "demo-import | job"
        string commitment
        float threshold
        bool simulated
        string results_sha256
    }
    attack_results {
        int id PK
        int attack_run_id FK
        string attack
        string family
        float accuracy
        float owner_ber
        bool survives
    }
    deployments {
        int id PK
        string name
        string environment
        string artifact_path
        string expected_sha256
        int model_artifact_id FK
        bool active
        string last_status
    }
    deployment_checks {
        int id PK
        int deployment_id FK
        string trigger "manual | scheduler"
        string status "ok | mismatch | missing | error"
        bool alert
        string observed_sha256
        bool registered
    }
    audit_events {
        bigint id PK
        bigint seq UK
        string ts
        string actor
        string action
        string resource_type
        string resource_id
        json details
        text event_json "canonical JSON that is hashed"
        string prev_hash
        string hash UK "SHA-256(prev_hash || event_json)"
    }
    result_snapshots {
        int id PK
        string name
        string path
        string sha256
        string commitment
        json content
        string source "demo-import | job:<id>"
    }
```

Notes:
* `audit_events` is append-only: triggers refuse UPDATE, DELETE and (PostgreSQL) TRUNCATE (DB-03). It has no
  foreign keys on purpose, so the log outlives the rows it describes.
* `result_snapshots` is unique on (`name`, `sha256`): each distinct version of a demo result file is kept once
  (DB-04).
* Signed records are stored as the exact text that was signed, so signatures re-verify byte for byte.
