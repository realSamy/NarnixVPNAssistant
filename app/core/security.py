import hmac
import time

SIGNATURE_HEADER = "x-narnix-signature"

# Same window as the Worker side — the two implementations must agree, or one
# side starts rejecting requests the other considers fresh.
REPLAY_WINDOW_SECONDS = 300


def sign_payload(secret: str, body: bytes) -> str:
    """Produces the `X-Narnix-Signature` header value for one request.

    HMAC-SHA256 over `<unix timestamp>.<raw body>`; the timestamp rides inside
    the signed material so a replayed header is worthless outside the window.
    """
    timestamp = int(time.time())
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, "sha256").hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_payload(secret: str, body: bytes, header: str | None) -> bool:
    """Verifies an inbound signature header against the raw request body."""
    if not header:
        return False

    parts = dict(
        piece.split("=", 1) for piece in header.strip().split(",") if "=" in piece
    )
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False

    if abs(time.time() - timestamp) > REPLAY_WINDOW_SECONDS:
        return False

    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, "sha256").hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))
