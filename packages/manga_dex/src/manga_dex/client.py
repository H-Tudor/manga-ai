from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from ai_translate import ImageTranslator
from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine, select

from .models import ChapterContentCache, ChapterListCache, MangaSearchCache, TranslatedPageCache


class MangaDexClient:
    BASE_URL = "https://api.mangadex.org"

    def __init__(
        self,
        db_url: str = "sqlite:///./manga_cache.db",
        storage_dir: str | Path = "./cache/translated",
        translator: ImageTranslator | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        load_dotenv()
        self.engine = create_engine(db_url)
        SQLModel.metadata.create_all(self.engine)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.translator = translator or ImageTranslator()
        self.client = http_client or httpx.AsyncClient(base_url=self.BASE_URL, timeout=30.0)

    async def close(self) -> None:
        await self.client.aclose()

    def _auth_headers(self) -> dict[str, str]:
        client_id = os.getenv("MANGADEX_CLIENT_ID")
        client_secret = os.getenv("MANGADEX_CLIENT_SECRET")
        headers: dict[str, str] = {}
        if client_id and client_secret:
            headers["X-Client-Id"] = client_id
            headers["X-Client-Secret"] = client_secret
        return headers

    @staticmethod
    def _language_rank(language: str) -> int:
        if language == "en":
            return 0
        if language in {"la", "it", "es", "fr", "pt", "ro"}:
            return 1
        return 2

    async def search_manga(self, title: str, limit: int = 10) -> list[dict[str, Any]]:
        key = title.strip().lower()
        with Session(self.engine) as session:
            cached = session.get(MangaSearchCache, key)
            if cached:
                return json.loads(cached.payload_json)

        response = await self.client.get(
            "/manga",
            params={"title": title, "limit": limit},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        data = response.json().get("data", [])

        parsed = [
            {
                "id": item.get("id"),
                "title": _extract_title(item.get("attributes", {}).get("title", {})),
                "description": _extract_title(item.get("attributes", {}).get("description", {})),
            }
            for item in data
        ]

        with Session(self.engine) as session:
            session.merge(MangaSearchCache(query=key, payload_json=json.dumps(parsed)))
            session.commit()
        return parsed

    async def get_chapters(self, manga_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return the chapter list for *manga_id*.

        Strategy: **live-first with DB fallback**.

        1. Attempt a live call to the MangaDex API.
        2. On success, persist the result to :class:`ChapterListCache` and
           return it (always fresh).
        3. On any network or HTTP error, fall back to the last cached result
           if one exists; otherwise re-raise the original exception.
        """
        exc_to_raise: Exception | None = None
        try:
            response = await self.client.get(
                "/chapter",
                params={"manga": manga_id, "limit": limit, "order[chapter]": "asc"},
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            data = response.json().get("data", [])

            chapters = [
                {
                    "id": chapter.get("id"),
                    "title": chapter.get("attributes", {}).get("title"),
                    "chapter": chapter.get("attributes", {}).get("chapter"),
                    "language": chapter.get("attributes", {}).get("translatedLanguage", "unknown"),
                }
                for chapter in data
            ]
            sorted_chapters = sorted(
                chapters,
                key=lambda c: (self._language_rank(c["language"]), c.get("chapter") or ""),
            )

            with Session(self.engine) as session:
                session.merge(
                    ChapterListCache(
                        manga_id=manga_id,
                        payload_json=json.dumps(sorted_chapters),
                    )
                )
                session.commit()

            return sorted_chapters

        except Exception as exc:  # noqa: BLE001
            exc_to_raise = exc

        # Fall back to cached data
        with Session(self.engine) as session:
            cached = session.get(ChapterListCache, manga_id)
            if cached:
                return json.loads(cached.payload_json)

        raise exc_to_raise

    async def _get_cached_chapter_content(self, chapter_id: str) -> tuple[str, list[str]] | None:
        with Session(self.engine) as session:
            cached = session.get(ChapterContentCache, chapter_id)
            if not cached:
                return None
            return cached.source_language, json.loads(cached.page_urls_json)

    async def _fetch_and_cache_chapter_content(self, chapter_id: str) -> tuple[str, list[str]]:
        details = await self.client.get(f"/chapter/{chapter_id}", headers=self._auth_headers())
        details.raise_for_status()
        details_json = details.json().get("data", {})
        source_language = details_json.get("attributes", {}).get("translatedLanguage", "unknown")

        at_home = await self.client.get(f"/at-home/server/{chapter_id}", headers=self._auth_headers())
        at_home.raise_for_status()
        chapter_data = at_home.json().get("chapter", {})
        base_url = at_home.json().get("baseUrl", "")
        chapter_hash = chapter_data.get("hash", "")
        pages = chapter_data.get("data", [])
        page_urls = [f"{base_url}/data/{chapter_hash}/{filename}" for filename in pages]

        with Session(self.engine) as session:
            session.merge(
                ChapterContentCache(
                    chapter_id=chapter_id,
                    source_language=source_language,
                    page_urls_json=json.dumps(page_urls),
                )
            )
            session.commit()

        return source_language, page_urls

    async def get_chapter_images(self, chapter_id: str, target_language: str = "en") -> list[dict[str, Any]]:
        cached = await self._get_cached_chapter_content(chapter_id)
        if cached:
            source_language, page_urls = cached
        else:
            source_language, page_urls = await self._fetch_and_cache_chapter_content(chapter_id)

        images: list[dict[str, Any]] = []
        for idx, page_url in enumerate(page_urls):
            translated_file = self.storage_dir / f"{chapter_id}_{idx}_{target_language}.img"
            if target_language == "en" and source_language != "en":
                with Session(self.engine) as session:
                    existing = session.exec(
                        select(TranslatedPageCache).where(
                            TranslatedPageCache.chapter_id == chapter_id,
                            TranslatedPageCache.page_index == idx,
                            TranslatedPageCache.target_language == target_language,
                        )
                    ).first()
                    if existing and Path(existing.file_path).exists():
                        images.append({"page_index": idx, "type": "translated", "path": existing.file_path})
                        continue

                original = await self.client.get(page_url)
                original.raise_for_status()
                translated = await self.translator.translate_image(
                    original.content,
                    source_language=source_language,
                    target_language=target_language,
                )
                translated_file.write_bytes(translated)
                with Session(self.engine) as session:
                    session.add(
                        TranslatedPageCache(
                            chapter_id=chapter_id,
                            page_index=idx,
                            target_language=target_language,
                            file_path=str(translated_file),
                        )
                    )
                    session.commit()
                images.append({"page_index": idx, "type": "translated", "path": str(translated_file)})
            else:
                images.append({"page_index": idx, "type": "remote", "url": page_url})
        return images

    async def get_page_bytes(self, chapter_id: str, page_index: int, target_language: str = "en") -> bytes:
        pages = await self.get_chapter_images(chapter_id=chapter_id, target_language=target_language)
        page = next((item for item in pages if item["page_index"] == page_index), None)
        if not page:
            raise ValueError("Page index not found")

        if page["type"] == "translated":
            return Path(page["path"]).read_bytes()

        response = await self.client.get(page["url"])
        response.raise_for_status()
        return response.content


def _extract_title(values: dict[str, str]) -> str:
    if not values:
        return ""
    if "en" in values:
        return values["en"]
    return next(iter(values.values()))
