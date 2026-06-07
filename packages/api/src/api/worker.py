"""Background worker for asynchronous manga translation.

The worker maintains a single :class:`asyncio.Queue` that accepts
:class:`TranslationTask` items.  A long-running asyncio task
(:func:`start_worker`) drains the queue sequentially, translating every
chapter of the requested manga one by one and persisting progress to the
:class:`~manga_dex.models.ProcessingJob` table.

Starting / stopping
-------------------
The worker is integrated with the FastAPI application lifespan so it starts
when the server boots and is gracefully cancelled on shutdown.  It is
**not** started automatically when this module is imported — call
:func:`start_worker` explicitly (or let the lifespan handler do it).

Usage::

    from api.worker import enqueue, JobQueue
    job_id = await enqueue(manga_id="abc123", manga_title="Naruto", db_engine=engine)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Session, select

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from manga_dex.client import MangaDexClient
    from manga_dex.models import ProcessingJob

logger = logging.getLogger(__name__)


@dataclass
class TranslationTask:
    """A unit of work for the background worker."""

    job_id: int
    manga_id: str
    target_language: str


# Module-level queue shared across the application
_queue: asyncio.Queue[TranslationTask] = asyncio.Queue()
_worker_task: asyncio.Task | None = None


async def enqueue(
    manga_id: str,
    manga_title: str,
    engine: "Engine",
    target_language: str = "en",
) -> int:
    """Create a :class:`~manga_dex.models.ProcessingJob` row and enqueue it.

    Parameters
    ----------
    manga_id:
        MangaDex manga UUID.
    manga_title:
        Human-readable title (stored for display purposes).
    engine:
        SQLAlchemy engine connected to the application database.
    target_language:
        BCP-47 target language code (default ``"en"``).

    Returns
    -------
    int
        The newly created job ID.
    """
    from manga_dex.models import ProcessingJob

    job = ProcessingJob(
        manga_id=manga_id,
        manga_title=manga_title,
        target_language=target_language,
        status="pending",
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id: int = job.id  # type: ignore[assignment]

    await _queue.put(TranslationTask(job_id=job_id, manga_id=manga_id, target_language=target_language))
    logger.info("Enqueued translation job %d for manga %s", job_id, manga_id)
    return job_id


def _update_job(engine: "Engine", job_id: int, **kwargs: object) -> None:
    """Patch arbitrary fields on a :class:`~manga_dex.models.ProcessingJob`."""
    from manga_dex.models import ProcessingJob

    with Session(engine) as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


async def _process_task(task: TranslationTask, client: "MangaDexClient", engine: "Engine") -> None:
    """Fetch and translate every chapter for a single manga."""
    from manga_dex.models import ProcessingJob

    _update_job(engine, task.job_id, status="running")

    try:
        chapters = await client.get_chapters(task.manga_id)
        _update_job(engine, task.job_id, total_chapters=len(chapters))

        for idx, chapter in enumerate(chapters):
            chapter_id: str = chapter["id"]
            try:
                await client.get_chapter_images(
                    chapter_id=chapter_id,
                    target_language=task.target_language,
                )
                logger.info("Job %d: translated chapter %s (%d/%d)", task.job_id, chapter_id, idx + 1, len(chapters))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Job %d: skipping chapter %s – %s", task.job_id, chapter_id, exc)

            _update_job(engine, task.job_id, processed_chapters=idx + 1)

        _update_job(engine, task.job_id, status="completed")
        logger.info("Job %d completed", task.job_id)

    except Exception as exc:  # noqa: BLE001
        logger.error("Job %d failed: %s", task.job_id, exc)
        _update_job(engine, task.job_id, status="failed", error=str(exc))


async def _worker_loop(client: "MangaDexClient", engine: "Engine") -> None:
    """Continuously drain the queue until the task is cancelled."""
    while True:
        task = await _queue.get()
        try:
            await _process_task(task, client, engine)
        finally:
            _queue.task_done()


def start_worker(client: "MangaDexClient", engine: "Engine") -> asyncio.Task:
    """Start the background worker coroutine and return its :class:`asyncio.Task`.

    This must be called from within a running event loop (e.g. inside an
    ``async with lifespan()`` block).

    Parameters
    ----------
    client:
        A :class:`~manga_dex.client.MangaDexClient` used to fetch and translate
        chapters.
    engine:
        The shared SQLAlchemy engine for persisting job status.
    """
    global _worker_task  # noqa: PLW0603
    _worker_task = asyncio.create_task(_worker_loop(client, engine))
    logger.info("Background translation worker started")
    return _worker_task


def stop_worker() -> None:
    """Cancel the background worker task (call during application shutdown)."""
    global _worker_task  # noqa: PLW0603
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        logger.info("Background translation worker stopped")
    _worker_task = None
