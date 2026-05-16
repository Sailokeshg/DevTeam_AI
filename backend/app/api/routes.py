"""Core API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    """Simple service health endpoint."""
    return {"status": "ok"}
