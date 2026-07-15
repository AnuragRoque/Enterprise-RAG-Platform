import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import (
    Project, Document, DocumentChunk, IngestJob,
    ScopeEnum, DocTypeEnum, JobStateEnum, AdminUser,
    ApiRequestLog, AllowedDomain,
)
from core.config import settings
from core.app_settings import DEFAULT_SETTINGS, get_all_settings, set_setting
from app.api.auth import require_admin
from ingestion.analyzer import analyze_file

# Every route here requires a valid admin session.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


@router.get("/config")
def get_config():
    """Non-secret-ish config the admin UI needs to build embed snippets.

    The chatbot API key is already served publicly inside /static/chatbot.js, so
    surfacing it here (behind admin auth) exposes nothing new.
    """
    from ingestion.parser import glm_ocr_available, TESSERACT_AVAILABLE
    return {
        "chatbot_api_key": settings.chatbot_api_key,
        "generation_model": settings.default_generation_model,
        "embedding_model": settings.embedding_model,
        "ollama_base_url": settings.ollama_base_url,
        "global_project_slug": settings.global_project_slug,
        "ocr_model": settings.ocr_model,
        "ocr_vision_available": glm_ocr_available(timeout=1.5),
        "tesseract_available": TESSERACT_AVAILABLE,
    }


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.id).all()
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    result = []
    for p in projects:
        doc_count = db.query(func.count(Document.id)).filter(Document.project_id == p.id).scalar()
        hits_24h = (
            db.query(func.count(ApiRequestLog.id))
            .filter(ApiRequestLog.project_id == p.id, ApiRequestLog.created_at >= since_24h)
            .scalar()
        )
        result.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "description": p.description,
            "status": p.status or "active",
            "doc_count": doc_count or 0,
            "hits_24h": hits_24h or 0,
            "is_global": p.slug == settings.global_project_slug,
            "created_at": _iso(p.created_at),
            "updated_at": _iso(p.updated_at),
        })
    return result


@router.post("/projects")
def create_project(data: dict, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    slug = name.lower().replace(" ", "-")
    if db.query(Project).filter(Project.slug == slug).first():
        raise HTTPException(status_code=409, detail="A project with this name already exists")
    project = Project(name=name, slug=slug, description=(data.get("description") or "").strip() or None)
    db.add(project)
    db.commit()
    return {"id": project.id, "slug": project.slug}


@router.patch("/projects/{slug}")
def update_project(slug: str, data: dict, db: Session = Depends(get_db)):
    """Edit name / description, or enable/disable the project.

    The slug is permanent on purpose — embed snippets and API URLs out in the
    wild keep working across renames.
    """
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        project.name = name

    if "description" in data:
        project.description = (data.get("description") or "").strip() or None

    if "status" in data:
        status_value = data.get("status")
        if status_value not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="status must be 'active' or 'disabled'")
        if status_value == "disabled" and project.slug == settings.global_project_slug:
            raise HTTPException(
                status_code=400,
                detail="The global knowledge base is switched off from Settings → Global knowledge base instead.",
            )
        project.status = status_value

    # onupdate only fires when a column changes; touch it explicitly so a no-op
    # save still reads as an update in the panel.
    project.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": "ok",
        "project": {
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "project_status": project.status,
            "updated_at": _iso(project.updated_at),
        },
    }


@router.get("/projects/{slug}/documents")
def list_documents(slug: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    docs = db.query(Document).filter(Document.project_id == project.id).order_by(Document.id.desc()).all()
    result = []
    for d in docs:
        n_chunks = db.query(func.count(DocumentChunk.id)).filter(DocumentChunk.document_id == d.id).scalar() or 0
        job = (
            db.query(IngestJob)
            .filter(IngestJob.document_id == d.id)
            .order_by(IngestJob.id.desc())
            .first()
        )
        job_state = job.state.value if job and job.state else None
        # Present a friendly, user-facing status.
        if d.needs_review:
            ui_status = "review"
        elif n_chunks > 0:
            ui_status = "indexed"
        elif job_state in ("queued", "running"):
            ui_status = "processing"
        elif job_state == "failed":
            ui_status = "failed"
        else:
            ui_status = "pending"
        result.append({
            "id": d.id,
            "title": d.title,
            "n_chunks": n_chunks,
            "status": ui_status,
            "error": job.error if job and job.error else None,
            "needs_review": bool(d.needs_review),
            "processing_mode": d.processing_mode,
            "ocr_engine": d.ocr_engine,
            "rich_content": d.rich_content,
            "created_at": _iso(d.created_at),
        })
    return result


def _validate_upload(file: UploadFile, data: bytes) -> None:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.allowed_extensions_set:
        allowed = ", ".join(sorted(e.lstrip(".") for e in settings.allowed_extensions_set))
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext or file.filename}'. Allowed: {allowed}.")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail=f"'{file.filename}' is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"'{file.filename}' exceeds the {settings.max_upload_mb} MB limit.",
        )


@router.post("/projects/{slug}/documents")
async def upload_documents(
    slug: str,
    files: List[UploadFile] = File(...),
    content_hint: str = Form("auto"),
    db: Session = Depends(get_db),
):
    """Upload documents, pre-scan them for rich content, and queue or park them.

    content_hint is the uploader's answer to "does this contain images / charts /
    tables / scans?" — 'auto' | 'rich' | 'plain'. Routing logic: ocrplan.md §4.
    """
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if content_hint not in ("auto", "rich", "plain"):
        content_hint = "auto"

    os.makedirs("data", exist_ok=True)

    is_global = project.slug == settings.global_project_slug
    scope = ScopeEnum.company if is_global else ScopeEnum.project
    doc_type = DocTypeEnum.policy if is_global else DocTypeEnum.documentation

    results = []
    for file in files:
        try:
            data = await file.read()
            _validate_upload(file, data)
        except HTTPException as exc:
            results.append({"filename": file.filename, "status": "error", "message": exc.detail})
            continue

        file_id = str(uuid.uuid4())
        # Strip any path components from the client filename before joining.
        safe_name = Path(file.filename).name
        file_path = os.path.join("data", f"{file_id}_{safe_name}")
        with open(file_path, "wb") as f:
            f.write(data)

        # Instant rich-content pre-scan (PyMuPDF signals only, no OCR).
        detection = analyze_file(file_path)
        is_rich = bool(detection and detection.get("is_rich"))

        if content_hint == "rich":
            mode, park = "deep", False
        elif content_hint == "plain":
            # User said plain text; if the pre-scan disagrees, park the file and
            # ask instead of silently degrading their tables and charts.
            mode, park = "standard", is_rich
        else:  # auto
            mode, park = ("deep" if is_rich else "standard"), False

        doc = Document(
            title=safe_name,
            project_id=project.id,
            source_path=file_path,
            scope=scope,
            doc_type=doc_type,
            status="active",
            content_hint=content_hint,
            processing_mode=mode,
            rich_content=detection,
            needs_review=park,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        if park:
            results.append({
                "filename": safe_name, "status": "needs_review",
                "document_id": doc.id, "detection": detection,
            })
        else:
            db.add(IngestJob(document_id=doc.id, state=JobStateEnum.queued))
            db.commit()
            results.append({
                "filename": safe_name, "status": "queued",
                "document_id": doc.id, "mode": mode, "detection": detection,
            })

    queued = sum(1 for r in results if r["status"] == "queued")
    review = sum(1 for r in results if r["status"] == "needs_review")
    failed = [r for r in results if r["status"] == "error"]
    message = f"{queued} document(s) queued for processing."
    if review:
        message += f" {review} awaiting your confirmation (rich content detected)."
    if failed:
        message += f" {len(failed)} failed."
    return {
        "status": "ok" if not failed else "partial",
        "queued": queued,
        "needs_review": review,
        "failed": len(failed),
        "results": results,
        "message": message,
    }


@router.post("/projects/{slug}/documents/{doc_id}/process")
def confirm_document_processing(slug: str, doc_id: int, data: dict, db: Session = Depends(get_db)):
    """Resolve a parked (needs_review) document — or re-queue any document —
    with an explicit processing mode: 'deep' (vision OCR) or 'standard'."""
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    doc = db.query(Document).filter(Document.id == doc_id, Document.project_id == project.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    mode = data.get("mode")
    if mode not in ("deep", "standard"):
        raise HTTPException(status_code=400, detail="mode must be 'deep' or 'standard'")

    doc.processing_mode = mode
    doc.needs_review = False
    db.add(IngestJob(document_id=doc.id, state=JobStateEnum.queued))
    db.commit()
    label = "deep scan (vision OCR)" if mode == "deep" else "standard text extraction"
    return {"status": "ok", "message": f"Queued with {label}."}


@router.delete("/projects/{slug}/documents/{doc_id}")
def delete_document(slug: str, doc_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = db.query(Document).filter(
        Document.id == doc_id, Document.project_id == project.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove ingest jobs (no cascade on the FK), then the file on disk.
    db.query(IngestJob).filter(IngestJob.document_id == doc.id).delete()

    if doc.source_path and os.path.exists(doc.source_path):
        try:
            os.remove(doc.source_path)
        except OSError:
            pass

    # Deleting the document cascades to its chunks (relationship cascade).
    db.delete(doc)
    db.commit()

    return {"status": "ok", "message": "Document deleted."}


# --------------------------------------------------------------------------- #
# Platform settings (global toggles)
# --------------------------------------------------------------------------- #

@router.get("/settings")
def get_platform_settings(db: Session = Depends(get_db)):
    return get_all_settings(db)


@router.put("/settings")
def update_platform_settings(data: dict, db: Session = Depends(get_db)):
    unknown = [k for k in data if k not in DEFAULT_SETTINGS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown setting(s): {', '.join(unknown)}")
    for key, value in data.items():
        set_setting(db, key, bool(value))
    return {"status": "ok", "settings": get_all_settings(db)}


# --------------------------------------------------------------------------- #
# API monitor
# --------------------------------------------------------------------------- #

@router.get("/metrics/summary")
def metrics_summary(db: Session = Depends(get_db)):
    """Everything the API Monitor dashboard shows in one call."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    total = db.query(func.count(ApiRequestLog.id)).scalar() or 0
    last_24h = db.query(func.count(ApiRequestLog.id)).filter(ApiRequestLog.created_at >= since_24h).scalar() or 0
    avg_latency = db.query(func.avg(ApiRequestLog.latency_ms)).filter(ApiRequestLog.created_at >= since_24h).scalar()
    blocked_24h = (
        db.query(func.count(ApiRequestLog.id))
        .filter(ApiRequestLog.created_at >= since_24h, ApiRequestLog.status_code >= 400)
        .scalar() or 0
    )

    by_project = (
        db.query(ApiRequestLog.project_slug, func.count(ApiRequestLog.id).label("n"))
        .group_by(ApiRequestLog.project_slug)
        .order_by(func.count(ApiRequestLog.id).desc())
        .limit(12)
        .all()
    )
    name_by_slug = {p.slug: p.name for p in db.query(Project).all()}

    by_origin = (
        db.query(
            ApiRequestLog.origin,
            func.count(ApiRequestLog.id).label("n"),
            func.max(ApiRequestLog.created_at).label("last_at"),
        )
        .group_by(ApiRequestLog.origin)
        .order_by(func.count(ApiRequestLog.id).desc())
        .limit(12)
        .all()
    )

    # Hourly buckets for the last 24 h, zero-filled so the chart has 24 bars.
    hour_rows = (
        db.query(
            func.date_trunc('hour', ApiRequestLog.created_at).label("h"),
            func.count(ApiRequestLog.id).label("n"),
        )
        .filter(ApiRequestLog.created_at >= since_24h)
        .group_by("h")
        .all()
    )
    counts_by_hour = {row.h.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0): row.n
                      for row in hour_rows if row.h}
    hourly = []
    cursor = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    for _ in range(24):
        hourly.append({"hour": cursor.isoformat(), "count": counts_by_hour.get(cursor, 0)})
        cursor += timedelta(hours=1)

    return {
        "total": total,
        "last_24h": last_24h,
        "avg_latency_ms": round(avg_latency) if avg_latency is not None else None,
        "blocked_24h": blocked_24h,
        "by_project": [
            {"slug": slug or "(unknown)", "name": name_by_slug.get(slug, slug or "(unknown)"), "count": n}
            for slug, n in by_project
        ],
        "by_origin": [
            {"origin": origin or "direct", "count": n, "last_at": _iso(last_at)}
            for origin, n, last_at in by_origin
        ],
        "hourly": hourly,
    }


@router.get("/metrics/requests")
def metrics_requests(limit: int = 50, db: Session = Depends(get_db)):
    """Most recent chat-API requests — the live feed."""
    limit = max(1, min(limit, 200))
    rows = db.query(ApiRequestLog).order_by(ApiRequestLog.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "project_slug": r.project_slug,
            "origin": r.origin,
            "client_ip": r.client_ip,
            "status_code": r.status_code,
            "latency_ms": r.latency_ms,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


@router.post("/metrics/demo-data")
def seed_demo_traffic(db: Session = Depends(get_db)):
    """Insert clearly-labelled sample traffic so the dashboard can be demoed
    before any real sites are wired up. Demo rows use demo.* origins."""
    slugs = [p.slug for p in db.query(Project).all()] or ["general-policy"]
    demo_origins = [
        "https://demo.acme-corp.example", "https://demo.hrportal.example",
        "https://demo.helpdesk.example", "direct",
    ]
    now = datetime.now(timezone.utc)
    rows = []
    for _ in range(160):
        status = random.choices([200, 200, 200, 200, 200, 200, 200, 200, 403, 404], k=1)[0]
        rows.append(ApiRequestLog(
            project_slug=random.choice(slugs),
            path="/api/demo/v1/chat/completions",
            method="POST",
            origin=random.choice(demo_origins),
            client_ip=f"203.0.113.{random.randint(1, 254)}",
            user_agent="demo-traffic-seed",
            status_code=status,
            latency_ms=random.randint(240, 2600),
            created_at=now - timedelta(minutes=random.randint(0, 24 * 60)),
        ))
    db.add_all(rows)
    db.commit()
    return {"status": "ok", "inserted": len(rows), "message": f"Inserted {len(rows)} sample requests (origins demo.*)."}


# --------------------------------------------------------------------------- #
# Domain whitelist
# --------------------------------------------------------------------------- #

_DOMAIN_RE = re.compile(r"^(localhost|(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+)$")


def _normalize_domain(raw: str) -> str:
    """Accept 'https://docs.example.com/path', 'docs.example.com:8080', etc. —
    store the bare lowercase hostname."""
    d = (raw or "").strip().lower()
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0].split(":", 1)[0].strip().rstrip(".")
    return d


@router.get("/domains")
def list_domains(db: Session = Depends(get_db)):
    name_by_id = {p.id: {"name": p.name, "slug": p.slug} for p in db.query(Project).all()}
    rows = db.query(AllowedDomain).order_by(AllowedDomain.id.desc()).all()
    return [
        {
            "id": r.id,
            "domain": r.domain,
            "note": r.note,
            "project": name_by_id.get(r.project_id),  # None = all projects
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


@router.post("/domains")
def add_domain(data: dict, db: Session = Depends(get_db)):
    domain = _normalize_domain(data.get("domain") or "")
    if not domain or not _DOMAIN_RE.match(domain):
        raise HTTPException(status_code=400, detail="Enter a valid domain, e.g. docs.example.com")

    project_id = None
    project_slug = (data.get("project_slug") or "").strip()
    if project_slug:
        project = db.query(Project).filter(Project.slug == project_slug).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project_id = project.id

    exists = db.query(AllowedDomain).filter(
        AllowedDomain.domain == domain, AllowedDomain.project_id == project_id
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="That domain is already whitelisted for this scope")

    row = AllowedDomain(domain=domain, project_id=project_id, note=(data.get("note") or "").strip() or None)
    db.add(row)
    db.commit()
    return {"status": "ok", "id": row.id, "domain": domain}


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: int, db: Session = Depends(get_db)):
    row = db.query(AllowedDomain).filter(AllowedDomain.id == domain_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Domain entry not found")
    db.delete(row)
    db.commit()
    return {"status": "ok", "message": "Domain removed from whitelist."}
