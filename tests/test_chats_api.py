import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import sign_payload
from app.routers import chats

SECRET = "test-secret"


class FakeRedis:
    """Just the four operations the router uses, on a dict."""

    def __init__(self):
        self.data: dict[str, str] = {}

    async def incr(self, key: str) -> int:
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    async def expire(self, key: str, ttl: int) -> None:
        pass

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True


class FakeRunner:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def schedule(self, session_id: str, message) -> None:
        self.calls.append((session_id, message))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AI_CALLBACK_SECRET", SECRET)
    monkeypatch.setenv("WORKER_CALLBACK_URL", "https://worker.example/ai/callback")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(chats.router)
    app.state.redis = FakeRedis()
    app.state.runner = FakeRunner()

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _post(client: TestClient, body: bytes, session_id: str = "s1"):
    return client.post(
        f"/api/v1/chats/{session_id}/messages",
        content=body,
        headers={
            "content-type": "application/json",
            "x-narnix-signature": sign_payload(SECRET, body),
        },
    )


def _message_body(count: int = 1) -> bytes:
    import json

    return json.dumps(
        {
            "chat_id": 42,
            "thread_id": 7,
            "user": {"id": 1000, "first_name": "Ali"},
            "text": "hello",
            "message_count": count,
            "message_limit": 20,
        }
    ).encode()


def test_unsigned_request_rejected(client):
    response = client.post(
        "/api/v1/chats/s1/messages", content=_message_body(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 401


def test_tampered_signature_rejected(client):
    body = _message_body()
    header = sign_payload(SECRET, body + b" ")
    response = client.post(
        "/api/v1/chats/s1/messages", content=body, headers={"x-narnix-signature": header}
    )
    assert response.status_code == 401


def test_signed_message_accepted_and_scheduled(client):
    response = _post(client, _message_body())
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(client.app.state.runner.calls) == 1


def test_duplicate_message_is_noop(client):
    _post(client, _message_body(count=3))
    response = _post(client, _message_body(count=3))
    assert response.json()["duplicate"] is True
    assert len(client.app.state.runner.calls) == 1


def test_rate_limit_returns_429(client):
    for i in range(1, 21):
        assert _post(client, _message_body(count=i)).status_code == 202
    assert _post(client, _message_body(count=21)).json()["status"] == "rate_limited"
    assert len(client.app.state.runner.calls) == 20
