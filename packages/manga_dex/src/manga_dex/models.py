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


class ChapterContentCache(SQLModel, table=True):
    chapter_id: str = Field(primary_key=True)
    source_language: str
    page_urls_json: str
    updated_at: datetime = Field(default_factory=now_utc)


class TranslatedPageCache(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chapter_id: str = Field(index=True)
    page_index: int = Field(index=True)
    target_language: str = Field(index=True)
    file_path: str
    created_at: datetime = Field(default_factory=now_utc)
