from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from manga_dex import MangaDexClient
from pydantic import BaseModel
from sqlmodel import Session, select

from .auth import UserInfo, require_auth
from .worker import enqueue, start_worker, stop_worker


# ---------------------------------------------------------------------------
# Shared client / engine helpers
# ---------------------------------------------------------------------------

_client_instance: MangaDexClient | None = None


def _make_client() -> MangaDexClient:
    return MangaDexClient(
        db_url=os.getenv("MANGA_DB_URL", "sqlite:///./manga_cache.db"),
        storage_dir=os.getenv("MANGA_STORAGE_DIR", "./cache/translated"),
    )


def get_client() -> MangaDexClient:
    global _client_instance  # noqa: PLW0603
    if _client_instance is None:
        _client_instance = _make_client()
    return _client_instance


# ---------------------------------------------------------------------------
# Application lifespan – starts / stops background worker
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    client = get_client()
    worker_task = start_worker(client, client.engine)
    try:
        yield
    finally:
        stop_worker()
        await client.close()


app = FastAPI(title="Manga AI API", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Protected endpoints (****** required)
# ---------------------------------------------------------------------------


@app.get("/manga/search")
async def search_manga(
    query: str = Query(..., min_length=1),
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> dict[str, object]:
    results = await client.search_manga(query)
    return {"results": results}


@app.get("/manga/{manga_id}/chapters")
async def manga_chapters(
    manga_id: str,
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> dict[str, object]:
    chapters = await client.get_chapters(manga_id)
    return {"chapters": chapters}


@app.get("/chapters/{chapter_id}")
async def chapter_images(
    chapter_id: str,
    target_language: str = "en",
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> dict[str, object]:
    images = await client.get_chapter_images(chapter_id, target_language)
    for page in images:
        page["endpoint"] = f"/chapters/{chapter_id}/images/{page['page_index']}?target_language={target_language}"
    return {"chapter_id": chapter_id, "images": images}


@app.get("/chapters/{chapter_id}/images/{page_index}")
async def chapter_image(
    chapter_id: str,
    page_index: int,
    target_language: str = "en",
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> Response:
    try:
        content = await client.get_page_bytes(chapter_id, page_index, target_language=target_language)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=content, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Background processing (translation queue) endpoints
# ---------------------------------------------------------------------------


class EnqueueRequest(BaseModel):
    manga_title: str = ""
    target_language: str = "en"


@app.post("/manga/{manga_id}/enqueue", status_code=202)
async def enqueue_manga(
    manga_id: str,
    body: EnqueueRequest = EnqueueRequest(),
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> dict[str, object]:
    """Enqueue a manga for background chapter-by-chapter translation.

    Returns the job ID that can be polled via ``GET /jobs/{job_id}``.
    """
    job_id = await enqueue(
        manga_id=manga_id,
        manga_title=body.manga_title,
        engine=client.engine,
        target_language=body.target_language,
    )
    return {"job_id": job_id, "status": "pending"}


@app.get("/jobs/{job_id}")
async def get_job(
    job_id: int,
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> dict[str, object]:
    """Return the current status of a translation job."""
    from manga_dex.models import ProcessingJob

    with Session(client.engine) as session:
        job = session.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.id,
        "manga_id": job.manga_id,
        "manga_title": job.manga_title,
        "target_language": job.target_language,
        "status": job.status,
        "total_chapters": job.total_chapters,
        "processed_chapters": job.processed_chapters,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@app.get("/jobs")
async def list_jobs(
    client: MangaDexClient = Depends(get_client),
    _user: UserInfo = Depends(require_auth),
) -> dict[str, object]:
    """List all translation jobs, most recent first."""
    from manga_dex.models import ProcessingJob

    with Session(client.engine) as session:
        jobs = session.exec(select(ProcessingJob)).all()

    return {
        "jobs": [
            {
                "job_id": j.id,
                "manga_id": j.manga_id,
                "manga_title": j.manga_title,
                "target_language": j.target_language,
                "status": j.status,
                "total_chapters": j.total_chapters,
                "processed_chapters": j.processed_chapters,
                "created_at": j.created_at.isoformat(),
            }
            for j in reversed(jobs)
        ]
    }

