from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness: the process is up. No dependencies checked."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict:
    """Readiness: Redis answers. (Postgres is exercised by the checkpointer's
    own connection pool, and its setup failing at startup takes the whole
    process down — a readiness probe would never observe it degraded.)"""
    try:
        if not await request.app.state.redis.ping():
            raise RuntimeError("ping returned false")
    except Exception as err:
        raise HTTPException(status_code=503, detail=f"redis unavailable: {err}") from err

    return {"status": "ok"}
