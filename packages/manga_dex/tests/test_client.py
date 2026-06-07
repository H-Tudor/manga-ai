from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from manga_dex.client import MangaDexClient


@pytest.mark.asyncio
async def test_get_chapters_prioritizes_english_and_latin(tmp_path: Path):
    async def app(scope, receive, send):
        if scope["path"] == "/chapter":
            body = {
                "data": [
                    {"id": "1", "attributes": {"chapter": "3", "translatedLanguage": "ja"}},
                    {"id": "2", "attributes": {"chapter": "1", "translatedLanguage": "es"}},
                    {"id": "3", "attributes": {"chapter": "2", "translatedLanguage": "en"}},
                ]
            }
        else:
            body = {"data": []}
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": str(body).replace("'", '"').encode()})

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
async def test_translated_images_are_cached(tmp_path: Path):
    calls = {"image": 0}

    async def app(scope, receive, send):
        path = scope["path"]
        if path == "/chapter/ch1":
            body = {"data": {"attributes": {"translatedLanguage": "ja"}}}
            status = 200
            payload = str(body).replace("'", '"').encode()
        elif path == "/at-home/server/ch1":
            body = {
                "baseUrl": "https://api.mangadex.org",
                "chapter": {"hash": "abc", "data": ["1.jpg"]},
            }
            status = 200
            payload = str(body).replace("'", '"').encode()
        elif path == "/data/abc/1.jpg":
            calls["image"] += 1
            status = 200
            payload = b"raw-image"
        else:
            status = 404
            payload = b"{}"

        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": payload})

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
