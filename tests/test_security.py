import time

from app.core.security import REPLAY_WINDOW_SECONDS, sign_payload, verify_payload

SECRET = "test-secret"


def _signed_body(body: bytes) -> str:
    return sign_payload(SECRET, body)


def test_roundtrip():
    body = b'{"action": "answer"}'
    assert verify_payload(SECRET, body, _signed_body(body))


def test_rejects_missing_header():
    assert not verify_payload(SECRET, b"{}", None)


def test_rejects_tampered_body():
    header = _signed_body(b'{"action": "answer"}')
    assert not verify_payload(SECRET, b'{"action": "answer", "text": "evil"}', header)


def test_rejects_wrong_secret():
    body = b"{}"
    assert not verify_payload("other-secret", body, _signed_body(body))


def test_rejects_stale_timestamp():
    body = b"{}"
    stale = time.time() - REPLAY_WINDOW_SECONDS - 10
    mac = __import__("hmac").new(SECRET.encode(), f"{int(stale)}.".encode() + body, "sha256").hexdigest()
    header = f"t={int(stale)},v1={mac}"
    assert not verify_payload(SECRET, body, header)


def test_rejects_malformed_header():
    body = b"{}"
    assert not verify_payload(SECRET, body, "garbage")
    assert not verify_payload(SECRET, body, "t=abc,v1=00")
