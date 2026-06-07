import pytest
from fastapi.testclient import TestClient

from api.main import app, get_client


class DummyClient:
    async def search_manga(self, query):
        return [{"id": "m1", "title": query, "description": "desc"}]

    async def get_chapters(self, manga_id):
        return [{"id": "c1", "chapter": "1", "language": "en", "title": None}]

    async def get_chapter_images(self, chapter_id, target_language="en"):
        return [{"page_index": 0, "type": "remote", "url": "https://img"}]

    async def get_page_bytes(self, chapter_id, page_index, target_language="en"):
        return b"bytes"


@pytest.fixture
def client():
    app.dependency_overrides[get_client] = lambda: DummyClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_search_endpoint(client):
    response = client.get("/manga/search", params={"query": "Naruto"})
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "Naruto"
