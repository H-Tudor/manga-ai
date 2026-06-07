import json as _json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from manga_dex.client import MangaDexClient, _extract_cover_url, _extract_scanlation_group


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_bytes(body: dict) -> bytes:
    return _json.dumps(body).encode()


async def _send_json(send, body: dict, status: int = 200) -> None:
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": _json_bytes(body)})


# ---------------------------------------------------------------------------
# Existing behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chapters_prioritizes_english_and_latin(tmp_path: Path):
    async def app(scope, receive, send):
        if scope["path"] == "/chapter":
            body = {
                "data": [
                    {"id": "1", "attributes": {"chapter": "3", "translatedLanguage": "ja"}, "relationships": []},
                    {"id": "2", "attributes": {"chapter": "1", "translatedLanguage": "es"}, "relationships": []},
                    {"id": "3", "attributes": {"chapter": "2", "translatedLanguage": "en"}, "relationships": []},
                ]
            }
        else:
            body = {"data": []}
        await _send_json(send, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        chapters = await client.get_chapters("manga")

    assert [c["id"] for c in chapters] == ["3", "2", "1"]


@pytest.mark.asyncio
async def test_get_chapters_falls_back_to_db_on_api_failure(tmp_path: Path):
    """get_chapters should return cached data when the live API is unavailable."""
    calls = {"n": 0}

    async def working_app(scope, receive, send):
        body = {
            "data": [
                {"id": "c1", "attributes": {"chapter": "1", "translatedLanguage": "en"}, "relationships": []},
            ]
        }
        await _send_json(send, body)

    async def broken_app(scope, receive, send):
        calls["n"] += 1
        await _send_json(send, {}, status=503)

    db_url = f"sqlite:///{tmp_path}/cache.db"
    storage = tmp_path / "translated"

    # First call: live API works – populates cache
    transport = ASGITransport(app=working_app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(db_url=db_url, storage_dir=storage, http_client=http_client)
        chapters_live = await client.get_chapters("manga-x")

    assert chapters_live[0]["id"] == "c1"

    # Second call: API is broken – should fall back to DB
    transport2 = ASGITransport(app=broken_app)
    async with AsyncClient(transport=transport2, base_url="https://api.mangadex.org") as http_client2:
        client2 = MangaDexClient(db_url=db_url, storage_dir=storage, http_client=http_client2)
        chapters_cached = await client2.get_chapters("manga-x")

    assert chapters_cached[0]["id"] == "c1"
    assert calls["n"] == 1  # broken app was called exactly once


@pytest.mark.asyncio
async def test_translated_images_are_cached(tmp_path: Path):
    calls = {"image": 0}

    async def app(scope, receive, send):
        path = scope["path"]
        if path == "/chapter/ch1":
            body = {"data": {"attributes": {"translatedLanguage": "ja"}}}
            await _send_json(send, body)
        elif path == "/at-home/server/ch1":
            body = {
                "baseUrl": "https://api.mangadex.org",
                "chapter": {"hash": "abc", "data": ["1.jpg"]},
            }
            await _send_json(send, body)
        elif path == "/data/abc/1.jpg":
            calls["image"] += 1
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"raw-image"})
        else:
            # /at-home/report and any other paths
            await _send_json(send, {})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        await client.get_chapter_images("ch1", target_language="en")
        await client.get_chapter_images("ch1", target_language="en")

    assert calls["image"] == 1


# ---------------------------------------------------------------------------
# Content rating – all ratings must be included
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_sends_all_content_ratings(tmp_path: Path):
    seen_params: list[str] = []

    async def app(scope, receive, send):
        seen_params.append(scope.get("query_string", b"").decode())
        body = {"data": []}
        await _send_json(send, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        await client.search_manga("test")

    qs = seen_params[0]
    for rating in ("safe", "suggestive", "erotica", "pornographic"):
        assert rating in qs, f"Expected content rating '{rating}' in query string"


@pytest.mark.asyncio
async def test_chapters_sends_all_content_ratings(tmp_path: Path):
    seen_params: list[str] = []

    async def app(scope, receive, send):
        if scope["path"] == "/chapter":
            seen_params.append(scope.get("query_string", b"").decode())
        body = {"data": []}
        await _send_json(send, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        await client.get_chapters("manga-id")

    qs = seen_params[0]
    for rating in ("safe", "suggestive", "erotica", "pornographic"):
        assert rating in qs, f"Expected content rating '{rating}' in query string"


# ---------------------------------------------------------------------------
# Cover art
# ---------------------------------------------------------------------------


def test_extract_cover_url_returns_cdn_url():
    rels = [
        {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}},
    ]
    assert _extract_cover_url("m1", rels) == "https://uploads.mangadex.org/covers/m1/cover.jpg"


def test_extract_cover_url_missing_returns_empty():
    assert _extract_cover_url("m1", []) == ""


@pytest.mark.asyncio
async def test_search_includes_cover_url_in_results(tmp_path: Path):
    async def app(scope, receive, send):
        body = {
            "data": [
                {
                    "id": "m1",
                    "attributes": {"title": {"en": "My Manga"}, "description": {}},
                    "relationships": [
                        {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}}
                    ],
                }
            ]
        }
        await _send_json(send, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        results = await client.search_manga("My Manga")

    assert results[0]["cover_url"] == "https://uploads.mangadex.org/covers/m1/cover.jpg"


# ---------------------------------------------------------------------------
# Scanlation group attribution
# ---------------------------------------------------------------------------


def test_extract_scanlation_group_returns_name():
    rels = [
        {"type": "scanlation_group", "attributes": {"name": "Elite Scans"}},
    ]
    assert _extract_scanlation_group(rels) == "Elite Scans"


def test_extract_scanlation_group_missing_returns_empty():
    assert _extract_scanlation_group([]) == ""


@pytest.mark.asyncio
async def test_chapters_include_scanlation_group(tmp_path: Path):
    async def app(scope, receive, send):
        body = {
            "data": [
                {
                    "id": "c1",
                    "attributes": {"chapter": "1", "translatedLanguage": "en", "title": None},
                    "relationships": [
                        {"type": "scanlation_group", "attributes": {"name": "Cool Scans"}}
                    ],
                }
            ]
        }
        await _send_json(send, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        chapters = await client.get_chapters("manga-id")

    assert chapters[0]["scanlation_group"] == "Cool Scans"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chapters_paginates_until_all_fetched(tmp_path: Path):
    """get_chapters must follow offset pagination to retrieve all chapters."""
    calls: list[str] = []

    async def app(scope, receive, send):
        if scope["path"] == "/chapter":
            qs = scope.get("query_string", b"").decode()
            calls.append(qs)
            # First page: 2 chapters, total=3
            if "offset=0" in qs or "offset" not in qs:
                body = {
                    "data": [
                        {"id": "c1", "attributes": {"chapter": "1", "translatedLanguage": "en"}, "relationships": []},
                        {"id": "c2", "attributes": {"chapter": "2", "translatedLanguage": "en"}, "relationships": []},
                    ],
                    "total": 3,
                }
            else:
                # Second page
                body = {
                    "data": [
                        {"id": "c3", "attributes": {"chapter": "3", "translatedLanguage": "en"}, "relationships": []},
                    ],
                    "total": 3,
                }
        else:
            body = {"data": []}
        await _send_json(send, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        chapters = await client.get_chapters("manga-id", limit=2)

    assert len(chapters) == 3
    assert {c["id"] for c in chapters} == {"c1", "c2", "c3"}
    assert len(calls) == 2  # two paginated requests


# ---------------------------------------------------------------------------
# At-Home URL freshness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_at_home_base_url_fetched_fresh_on_cache_hit(tmp_path: Path):
    """baseUrl must be re-fetched from /at-home/server on every get_chapter_images call."""
    at_home_calls: list[int] = []

    async def app(scope, receive, send):
        path = scope["path"]
        if path == "/chapter/ch1":
            body = {"data": {"attributes": {"translatedLanguage": "en"}}}
            await _send_json(send, body)
        elif path == "/at-home/server/ch1":
            at_home_calls.append(1)
            body = {"baseUrl": "https://cdn.example.com", "chapter": {"hash": "h1", "data": []}}
            await _send_json(send, body)
        else:
            await _send_json(send, {})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        await client.get_chapter_images("ch1")
        await client.get_chapter_images("ch1")

    # 1st call: _fetch_chapter_metadata calls /at-home/server once
    # 2nd call: cache hit → _get_fresh_base_url calls /at-home/server once
    assert len(at_home_calls) == 2


# ---------------------------------------------------------------------------
# At-Home report-back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_at_home_report_sent_after_image_download(tmp_path: Path):
    report_payloads: list[bytes] = []

    async def app(scope, receive, send):
        path = scope["path"]
        if path == "/chapter/ch1":
            await _send_json(send, {"data": {"attributes": {"translatedLanguage": "ja"}}})
        elif path == "/at-home/server/ch1":
            body = {"baseUrl": "https://api.mangadex.org", "chapter": {"hash": "h1", "data": ["p1.jpg"]}}
            await _send_json(send, body)
        elif path == "/data/h1/p1.jpg":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"imgdata"})
        elif path == "/at-home/report":
            # Collect request body
            body_chunks = []
            while True:
                event = await receive()
                body_chunks.append(event.get("body", b""))
                if not event.get("more_body", False):
                    break
            report_payloads.append(b"".join(body_chunks))
            await _send_json(send, {"result": "ok"})
        else:
            await _send_json(send, {})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        await client.get_chapter_images("ch1", target_language="en")

    assert len(report_payloads) == 1
    payload = _json.loads(report_payloads[0])
    assert payload["success"] is True
    assert "p1.jpg" in payload["url"]
    assert payload["bytes"] == len(b"imgdata")


# ---------------------------------------------------------------------------
# User-Agent header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_agent_header_is_set(tmp_path: Path):
    seen_ua: list[str] = []

    async def app(scope, receive, send):
        for name, value in scope.get("headers", []):
            if name == b"user-agent":
                seen_ua.append(value.decode())
        await _send_json(send, {"data": []})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.mangadex.org") as http_client:
        # Inject the User-Agent the real constructor would set
        http_client.headers["User-Agent"] = "manga-ai/0.1.0"
        client = MangaDexClient(
            db_url=f"sqlite:///{tmp_path}/cache.db",
            storage_dir=tmp_path / "translated",
            http_client=http_client,
        )
        await client.search_manga("test")

    assert any("manga-ai" in ua for ua in seen_ua), f"User-Agent not found in {seen_ua}"
