"""Model uploads and embedding reports (API-03 models/embeddings, API-05)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..auth import actor, current_user, get_db, require
from ..models import Embedding, Model, ModelArtifact, Owner, User, WatermarkConfig
from ..problems import ProblemError, responses
from ..uploads import list_layers, store_upload
from . import schemas as S
from .common import Page, ensure_owns_owner, get_or_404, model_out
from .registry_routes import upsert_config

router = APIRouter(tags=["models"])


@router.post("/models", response_model=S.ModelOut, status_code=201, responses=responses(401, 403, 413, 415, 422),
             summary="Upload a model file (.pt, .h5, .keras, .onnx) as multipart/form-data",
             description="Size limit SIGIL_MAX_UPLOAD_BYTES (default 500 MB). The extension and magic bytes are "
                         "checked, the SHA-256 is computed on receipt, and the file is stored outside the static "
                         "root. Owners upload `watermarked` models; verifiers upload `suspect` models.")
async def upload_model(request: Request, file: UploadFile = File(...), name: str | None = Form(None),
                       description: str | None = Form(None),
                       purpose: Literal["watermarked", "suspect"] | None = Form(None),
                       user: User = Depends(require("owner", "verifier")), db: Session = Depends(get_db)):
    purpose = purpose or ("suspect" if user.role == "verifier" else "watermarked")
    if user.role == "verifier" and purpose != "suspect":
        raise ProblemError(403, "verifiers can only upload suspect models")
    s = request.app.state.settings
    info = await run_in_threadpool(store_upload, file.file, file.filename or "", s.uploads, s.max_upload_bytes)

    def save():
        m = Model(name=(name or info["filename"])[:200], description=description, purpose=purpose, created_by=user.id)
        m.artifacts.append(ModelArtifact(filename=info["filename"], stored_path=info["stored_path"],
                                         sha256=info["sha256"], size_bytes=info["size_bytes"],
                                         framework=info["framework"], extension=info["extension"],
                                         uploaded_by=user.id))
        db.add(m)
        db.flush()
        audit.append(db, actor(user), "model.uploaded", "model", m.id,
                     {"sha256": info["sha256"], "size_bytes": info["size_bytes"], "framework": info["framework"],
                      "purpose": purpose, "filename": info["filename"]})
        db.refresh(m, ["artifacts"])
        return model_out(m)

    return await run_in_threadpool(save)


@router.get("/models", summary="List uploaded models (filter by purpose or SHA-256)", response_model=list[S.ModelOut], responses=responses(401))
def list_models(page: Page = Depends(), purpose: Literal["watermarked", "suspect"] | None = None,
                sha256: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Model).options(selectinload(Model.artifacts)).order_by(Model.id)
    if purpose:
        q = q.where(Model.purpose == purpose)
    if sha256:
        q = q.where(Model.id.in_(select(ModelArtifact.model_id).where(ModelArtifact.sha256 == sha256.lower())))
    return [model_out(m) for m in db.scalars(q.limit(page.limit).offset(page.offset))]


@router.get("/models/{model_id}", summary="One model with its artefacts", response_model=S.ModelOut, responses=responses(401, 404))
def get_model(model_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return model_out(get_or_404(db, Model, model_id, "model"))


@router.get("/artifacts/{artifact_id}/layers", response_model=S.LayersOut, responses=responses(401, 404, 422),
            summary="Layers / weight tensors of an uploaded artefact (safe loaders only; cached)")
def artifact_layers(artifact_id: int, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    a = get_or_404(db, ModelArtifact, artifact_id, "artifact")
    if a.layers is None:
        layers = list_layers(Path(request.app.state.settings.uploads) / a.stored_path, a.extension)
        if layers is not None:
            a.layers = layers
            db.commit()                     # cache only (derived data, not audited)
    return {"artifact_id": a.id, "framework": a.framework, "layers": a.layers}


# ---------------------------------------------------------------------------------------------- embeddings
@router.post("/embeddings", response_model=S.EmbeddingOut, status_code=201, tags=["models"],
             responses=responses(401, 403, 404, 422),
             summary="Record an embedding report (the embedding itself runs where the seed is: `sigil embed`)")
def record_embedding(body: S.EmbeddingCreate, user: User = Depends(require("owner")), db: Session = Depends(get_db)):
    art = get_or_404(db, ModelArtifact, body.model_artifact_id, "artifact")
    owner = get_or_404(db, Owner, body.owner_id, "owner")
    ensure_owns_owner(user, owner)
    cfg_row = upsert_config(db, body.config)
    e = Embedding(model_artifact_id=art.id, owner_id=owner.id, watermark_config_id=cfg_row.id, status="reported",
                  metrics=body.metrics, created_by=user.id)
    db.add(e)
    db.flush()
    audit.append(db, actor(user), "embedding.recorded", "embedding", e.id,
                 {"artifact_sha256": art.sha256, "config_hash": cfg_row.config_hash})
    return {"id": e.id, "model_artifact_id": e.model_artifact_id, "owner_id": e.owner_id,
            "config_hash": cfg_row.config_hash, "status": e.status, "metrics": e.metrics, "created_at": e.created_at}


@router.get("/embeddings", summary="List embedding reports", response_model=list[S.EmbeddingOut], tags=["models"], responses=responses(401))
def list_embeddings(page: Page = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Embedding, WatermarkConfig.config_hash)
                      .join(WatermarkConfig, Embedding.watermark_config_id == WatermarkConfig.id, isouter=True)
                      .order_by(Embedding.id).limit(page.limit).offset(page.offset)).all()
    return [{"id": e.id, "model_artifact_id": e.model_artifact_id, "owner_id": e.owner_id, "config_hash": h,
             "status": e.status, "metrics": e.metrics, "created_at": e.created_at} for e, h in rows]
