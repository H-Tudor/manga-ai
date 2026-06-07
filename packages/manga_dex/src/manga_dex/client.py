from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from ai_translate import ImageTranslator
from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine, select

from .models import ChapterContentCache, ChapterListCache, MangaSearchCache, TranslatedPageCache

_ALL_CONTENT_RATINGS = ["safe", "suggestive", "erotica", "pornographic"]
_USER_AGENT = "manga-ai/0.1.0"
_AUTH_TOKEN_URL = (
    "https://auth.mangadex.org/realms/mangadex/protocol/openid-connect/token"
)


# ---------------------------------------------------------------------------
# Rate limiter – MangaDex policy: ~5 requests / second
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Token-bucket rate limiter (default: 5 req/s per MangaDex policy)."""

    def __init__(self, rate: float = 5.0) -> None:
        self._min_interval = 1.0 / rate
        self._last: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


# ---------------------------------------------------------------------------
# OAuth2 token cache
# ---------------------------------------------------------------------------


class _TokenCache:
    """Caches a MangaDex OAuth2 ****** until near-expiry."""

    def __init__(self) -> None:
        self._token: str = ""
        self._expires_at: float = 0.0

    def valid(self) -> bool:
        return bool(self._token) and time.monotonic() < self._expires_at

    def update(self, token: str, expires_in: int) -> None:
        self._token = token
        # 30-second safety margin before the declared expiry
        self._expires_at = time.monotonic() + expires_in - 30

    @property
    def token(self) -> str:
        return self._token


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
        self.client = http_client or httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={"User-Agent": _USER_AGENT},
        )
        self._limiter = _RateLimiter()
        self._token_cache = _TokenCache()

    async def close(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _get_auth_headers(self) -> dict[str, str]:
        """Return OAuth2 ****** headers when credentials are configured."""
        client_id = os.getenv("MANGADEX_CLIENT_ID")
        client_secret = os.getenv("MANGADEX_CLIENT_SECRET")
        if not client_id or not client_secret:
            return {}
        if not self._token_cache.valid():
            await self._limiter.acquire()
            resp = await self.client.post(
                _AUTH_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            self._token_cache.update(body["access_token"], body.get("expires_in", 300))
        return {"Authorization": f"******"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _language_rank(language: str) -> int:
        if language == "en":
            return 0
        if language in {"la", "it", "es", "fr", "pt", "ro"}:
            return 1
        return 2

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_manga(self, title: str, limit: int = 10) -> list[dict[str, Any]]:
        key = title.strip().lower()
        with Session(self.engine) as session:
            cached = session.get(MangaSearchCache, key)
            if cached:
                return json.loads(cached.payload_json)

        await self._limiter.acquire()
        response = await self.client.get(
            "/manga",
            params={
                "title": title,
                "limit": limit,
                "contentRating[]": _ALL_CONTENT_RATINGS,
                "includes[]": ["cover_art"],
            },
            headers=await self._get_auth_headers(),
        )
        response.raise_for_status()
        data = response.json().get("data", [])

        parsed = [
            {
                "id": item.get("id"),
                "title": _extract_title(item.get("attributes", {}).get("title", {})),
                "description": _extract_title(item.get("attributes", {}).get("description", {})),
                "cover_url": _extract_cover_url(
                    item.get("id", ""), item.get("relationships", [])
                ),
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

        1. Attempt live calls to the MangaDex API, paginating until all
           chapters have been retrieved.
        2. On success, persist the result to :class:`ChapterListCache` and
           return it (always fresh).
        3. On any network or HTTP error, fall back to the last cached result
           if one exists; otherwise re-raise the original exception.
        """
        exc_to_raise: Exception | None = None
        try:
            all_data: list[dict[str, Any]] = []
            offset = 0
            while True:
                await self._limiter.acquire()
                response = await self.client.get(
                    "/chapter",
                    params={
                        "manga": manga_id,
                        "limit": limit,
                        "offset": offset,
                        "order[chapter]": "asc",
                        "contentRating[]": _ALL_CONTENT_RATINGS,
                        "includes[]": ["scanlation_group"],
                    },
                    headers=await self._get_auth_headers(),
                )
                response.raise_for_status()
                body = response.json()
                page = body.get("data", [])
                all_data.extend(page)
                total = body.get("total", len(page))
                offset += len(page)
                if offset >= total or not page:
                    break

            chapters = [
                {
                    "id": chapter.get("id"),
                    "title": chapter.get("attributes", {}).get("title"),
                    "chapter": chapter.get("attributes", {}).get("chapter"),
                    "language": chapter.get("attributes", {}).get(
                        "translatedLanguage", "unknown"
                    ),
                    "scanlation_group": _extract_scanlation_group(
                        chapter.get("relationships", [])
                    ),
                }
                for chapter in all_data
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

    # ------------------------------------------------------------------
    # Chapter content / image helpers
    # ------------------------------------------------------------------

    async def _get_cached_chapter_content(
        self, chapter_id: str
    ) -> tuple[str, str, list[str]] | None:
        """Return (source_language, chapter_hash, page_filenames) from DB, or None."""
        with Session(self.engine) as session:
            cached = session.get(ChapterContentCache, chapter_id)
            if not cached:
                return None
            return (
                cached.source_language,
                cached.chapter_hash,
                json.loads(cached.page_filenames_json),
            )

    async def _fetch_chapter_metadata(
        self, chapter_id: str
    ) -> tuple[str, str, list[str], str]:
        """Fetch & cache chapter metadata; return (source_language, chapter_hash, page_filenames, base_url)."""
        await self._limiter.acquire()
        details = await self.client.get(
            f"/chapter/{chapter_id}", headers=await self._get_auth_headers()
        )
        details.raise_for_status()
        details_json = details.json().get("data", {})
        source_language = details_json.get("attributes", {}).get(
            "translatedLanguage", "unknown"
        )

        await self._limiter.acquire()
        at_home = await self.client.get(
            f"/at-home/server/{chapter_id}", headers=await self._get_auth_headers()
        )
        at_home.raise_for_status()
        chapter_data = at_home.json().get("chapter", {})
        base_url = at_home.json().get("baseUrl", "")
        chapter_hash = chapter_data.get("hash", "")
        page_filenames = chapter_data.get("data", [])

        with Session(self.engine) as session:
            session.merge(
                ChapterContentCache(
                    chapter_id=chapter_id,
                    source_language=source_language,
                    chapter_hash=chapter_hash,
                    page_filenames_json=json.dumps(page_filenames),
                )
            )
            session.commit()

        return source_language, chapter_hash, page_filenames, base_url

    async def _get_fresh_base_url(self, chapter_id: str) -> str:
        """Fetch a fresh (non-cached) At-Home base URL for *chapter_id*.

        At-Home ``baseUrl`` values are session-scoped (~15 min).  Never serve
        images from a cached URL; always retrieve a fresh one.
        """
        await self._limiter.acquire()
        at_home = await self.client.get(
            f"/at-home/server/{chapter_id}", headers=await self._get_auth_headers()
        )
        at_home.raise_for_status()
        return at_home.json().get("baseUrl", "")

    async def _report_at_home(
        self,
        url: str,
        success: bool,
        duration_ms: int,
        byte_count: int,
        cached: bool,
    ) -> None:
        """Send the At-Home report required by MangaDex ToS (best-effort)."""
        try:
            await self.client.post(
                "/at-home/report",
                json={
                    "url": url,
                    "success": success,
                    "bytes": byte_count,
                    "duration": duration_ms,
                    "cached": cached,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    async def get_chapter_images(
        self, chapter_id: str, target_language: str = "en"
    ) -> list[dict[str, Any]]:
        cached = await self._get_cached_chapter_content(chapter_id)
        if cached:
            source_language, chapter_hash, page_filenames = cached
            # At-Home baseUrl expires; always fetch a fresh one.
            base_url = await self._get_fresh_base_url(chapter_id)
        else:
            source_language, chapter_hash, page_filenames, base_url = (
                await self._fetch_chapter_metadata(chapter_id)
            )

        page_urls = [
            f"{base_url}/data/{chapter_hash}/{filename}" for filename in page_filenames
        ]

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
                        images.append(
                            {"page_index": idx, "type": "translated", "path": existing.file_path}
                        )
                        continue

                t0 = time.monotonic()
                try:
                    original = await self.client.get(page_url)
                    original.raise_for_status()
                    byte_count = len(original.content)
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    is_cached = original.headers.get("X-Cache", "") == "HIT"
                    await self._report_at_home(page_url, True, duration_ms, byte_count, is_cached)
                except Exception as exc:
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    await self._report_at_home(page_url, False, duration_ms, 0, False)
                    raise exc

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
                images.append(
                    {"page_index": idx, "type": "translated", "path": str(translated_file)}
                )
            else:
                images.append({"page_index": idx, "type": "remote", "url": page_url})
        return images

    async def get_page_bytes(
        self, chapter_id: str, page_index: int, target_language: str = "en"
    ) -> bytes:
        pages = await self.get_chapter_images(
            chapter_id=chapter_id, target_language=target_language
        )
        page = next((item for item in pages if item["page_index"] == page_index), None)
        if not page:
            raise ValueError("Page index not found")

        if page["type"] == "translated":
            return Path(page["path"]).read_bytes()

        t0 = time.monotonic()
        try:
            response = await self.client.get(page["url"])
            response.raise_for_status()
            byte_count = len(response.content)
            duration_ms = int((time.monotonic() - t0) * 1000)
            is_cached = response.headers.get("X-Cache", "") == "HIT"
            await self._report_at_home(page["url"], True, duration_ms, byte_count, is_cached)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            await self._report_at_home(page["url"], False, duration_ms, 0, False)
            raise exc
        return response.content


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_title(values: dict[str, str]) -> str:
    if not values:
        return ""
    if "en" in values:
        return values["en"]
    return next(iter(values.values()))


def _extract_cover_url(manga_id: str, relationships: list[dict[str, Any]]) -> str:
    """Return the full CDN URL for the cover art, or an empty string."""
    for rel in relationships:
        if rel.get("type") == "cover_art":
            filename = rel.get("attributes", {}).get("fileName", "")
            if filename:
                return f"https://uploads.mangadex.org/covers/{manga_id}/{filename}"
    return ""


def _extract_scanlation_group(relationships: list[dict[str, Any]]) -> str:
    """Return the name of the first scanlation group, or an empty string."""
    for rel in relationships:
        if rel.get("type") == "scanlation_group":
            return rel.get("attributes", {}).get("name", "")
    return ""
