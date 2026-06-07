"""Background worker for asynchronous manga translation.

The worker maintains a single :class:`asyncio.Queue` that accepts
:class:`TranslationTask` items.  A long-running asyncio task
(:func:`start_worker`) drains the queue sequentially, translating every
chapter of the requested manga one by one and persisting progress to the
:class:`~manga_dex.models.ProcessingJob` table.

Priority scheduling
-------------------
On-demand chapter requests (direct API calls) are always served before
background translation jobs advance to the next chapter.  Use the module-level
:func:`on_demand_request` context manager in endpoint handlers to register an
active on-demand request.  The background worker calls
:func:`background_checkpoint` before each chapter so it yields whenever any
on-demand request is in flight.  This mechanism is safe for concurrent,
multi-user scenarios because a counter tracks the number of active on-demand
requests and a shared :class:`asyncio.Event` is only reopened when the last
one completes.

Starting / stopping
-------------------
The worker is integrated with the FastAPI application lifespan so it starts
when the server boots and is gracefully cancelled on shutdown.  It is
**not** started automatically when this module is imported — call
:func:`start_worker` explicitly (or let the lifespan handler do it).

Usage::

    from api.worker import enqueue, on_demand_request, background_checkpoint
    job_id = await enqueue(manga_id="abc123", manga_title="Naruto", db_engine=engine)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Session

if TYPE_CHECKING:
    from manga_dex.client import MangaDexClient
    from sqlalchemy import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Priority scheduler
# ---------------------------------------------------------------------------


class PriorityScheduler:
    """Ensures on-demand API requests are served before background tasks advance.

    On-demand requests register themselves via :meth:`on_demand_request`.
    The background worker calls :meth:`background_checkpoint` before each
    chapter.  If any on-demand request is active the checkpoint blocks until
    all of them have completed, so the HTTP handler always gets a clear path
    to the rate-limited MangaDex API.

    This is safe under concurrent, multi-user load: the counter is only
    modified without yielding to the event loop, so there is no race between
    increment and gate-close / decrement and gate-open.
    """

    def __init__(self) -> None:
        self._on_demand_count: int = 0
        # Gate is SET (open) when no on-demand requests are active.
        self._gate: asyncio.Event = asyncio.Event()
        self._gate.set()

    @contextlib.asynccontextmanager
    async def on_demand_request(self) -> AsyncIterator[None]:
        """Context manager that marks an active on-demand request.

        Usage in endpoint handlers::

            async with scheduler.on_demand_request():
                result = await client.get_chapter_images(...)
        """
        self._on_demand_count += 1
        self._gate.clear()
        try:
            yield
        finally:
            self._on_demand_count -= 1
            if self._on_demand_count == 0:
                self._gate.set()

    async def background_checkpoint(self) -> None:
        """Yield to any pending on-demand requests before the next background step.

        Call this inside the background worker loop before each unit of work
        (e.g. before translating each chapter).  If no on-demand requests are
        active this returns immediately with no overhead.
        """
        if not self._gate.is_set():
            logger.debug("Background worker waiting for on-demand requests to complete")
            await self._gate.wait()


# Module-level scheduler shared across the application
_scheduler: PriorityScheduler = PriorityScheduler()


@contextlib.asynccontextmanager
async def on_demand_request() -> AsyncIterator[None]:
    """Module-level shortcut for :meth:`PriorityScheduler.on_demand_request`."""
    async with _scheduler.on_demand_request():
        yield


async def background_checkpoint() -> None:
    """Module-level shortcut for :meth:`PriorityScheduler.background_checkpoint`."""
    await _scheduler.background_checkpoint()


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
    engine: Engine,
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


def _update_job(engine: Engine, job_id: int, **kwargs: object) -> None:
    """Patch arbitrary fields on a :class:`~manga_dex.models.ProcessingJob`."""
    from manga_dex.models import ProcessingJob

    with Session(engine) as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(UTC)
        session.add(job)
        session.commit()


async def _process_task(task: TranslationTask, client: MangaDexClient, engine: Engine) -> None:
    """Fetch and translate every chapter for a single manga."""

    _update_job(engine, task.job_id, status="running")

    try:
        chapters = await client.get_chapters(task.manga_id)
        _update_job(engine, task.job_id, total_chapters=len(chapters))

        for idx, chapter in enumerate(chapters):
            # Yield to on-demand requests before processing each chapter so
            # that interactive users are never blocked by background jobs.
            await background_checkpoint()
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


async def _worker_loop(client: MangaDexClient, engine: Engine) -> None:
    """Continuously drain the queue until the task is cancelled."""
    while True:
        task = await _queue.get()
        try:
            await _process_task(task, client, engine)
        finally:
            _queue.task_done()


def start_worker(client: MangaDexClient, engine: Engine) -> asyncio.Task:
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
