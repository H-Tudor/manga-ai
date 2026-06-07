from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MangaSearchCache(SQLModel, table=True):
    query: str = Field(primary_key=True)
    payload_json: str
    updated_at: datetime = Field(default_factory=now_utc)


class ChapterListCache(SQLModel, table=True):
    """Cached chapter list for a manga, keyed by manga ID.

    Populated on every successful live API call so that subsequent requests
    can fall back to this data when the MangaDex API is unavailable.
    """

    manga_id: str = Field(primary_key=True)
    payload_json: str
    updated_at: datetime = Field(default_factory=now_utc)


class ChapterContentCache(SQLModel, table=True):
    chapter_id: str = Field(primary_key=True)
    source_language: str
    chapter_hash: str
    page_filenames_json: str
    updated_at: datetime = Field(default_factory=now_utc)


class TranslatedPageCache(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chapter_id: str = Field(index=True)
    page_index: int = Field(index=True)
    target_language: str = Field(index=True)
    file_path: str
    created_at: datetime = Field(default_factory=now_utc)


class ProcessingJob(SQLModel, table=True):
    """Tracks an asynchronous manga translation job.

    A job represents the background task of fetching and translating every
    chapter of a manga entry.  Status transitions::

        pending → running → completed
                          ↘ failed
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    manga_id: str = Field(index=True)
    manga_title: str = Field(default="")
    target_language: str = Field(default="en")
    status: str = Field(default="pending")  # pending | running | completed | failed
    total_chapters: int = Field(default=0)
    processed_chapters: int = Field(default=0)
    error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
