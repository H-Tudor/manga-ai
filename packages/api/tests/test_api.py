import pytest
from fastapi.testclient import TestClient

from api.auth import UserInfo, require_auth, _auth_disabled
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

    async def close(self):
        pass


def _dummy_user() -> UserInfo:
    return UserInfo(sub="test-user", email="test@example.com", preferred_username="testuser")


@pytest.fixture
def client():
    app.dependency_overrides[get_client] = lambda: DummyClient()
    app.dependency_overrides[require_auth] = _dummy_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth(monkeypatch):
    """Test client with AUTH_DISABLED=true – no dependency override needed."""
    monkeypatch.setenv("AUTH_DISABLED", "true")
    app.dependency_overrides[get_client] = lambda: DummyClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_search_endpoint(client):
    response = client.get("/manga/search", params={"query": "Naruto"})
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "Naruto"


def test_health_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_endpoint_requires_auth():
    """Without AUTH_DISABLED and without a token the endpoint must return 401."""
    app.dependency_overrides[get_client] = lambda: DummyClient()
    with TestClient(app) as test_client:
        response = test_client.get("/manga/search", params={"query": "Naruto"})
    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_auth_disabled_flag(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    assert _auth_disabled() is True
    monkeypatch.setenv("AUTH_DISABLED", "false")
    assert _auth_disabled() is False
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    assert _auth_disabled() is False


def test_search_endpoint_auth_disabled(client_no_auth):
    """When AUTH_DISABLED=true, requests without a token must succeed."""
    response = client_no_auth.get("/manga/search", params={"query": "Bleach"})
    assert response.status_code == 200
    assert response.json()["results"][0]["title"] == "Bleach"

