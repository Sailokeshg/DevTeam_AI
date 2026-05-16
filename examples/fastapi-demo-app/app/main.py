"""Small FastAPI demo app for DevTeam AI example runs."""

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

app = FastAPI(title="DevTeam AI Demo App")


class ItemCreate(BaseModel):
    """Input payload used by the validation demo task."""

    name: str = Field(min_length=2, max_length=80)
    quantity: int = Field(gt=0, le=100)


class ItemResponse(ItemCreate):
    """Response payload for created demo items."""

    id: str


class CurrentUser(BaseModel):
    """Authenticated user shape for the JWT skeleton demo task."""

    username: str
    scopes: list[str]


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health endpoint used by portfolio demo tasks."""
    return {"status": "ok"}


@app.get("/ping")
def ping() -> dict[str, str]:
    """Simple endpoint used by generated test examples."""
    return {"message": "pong"}


@app.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(item: ItemCreate) -> ItemResponse:
    """Create a demo item after Pydantic input validation."""
    slug = item.name.lower().replace(" ", "-")
    return ItemResponse(id=f"item-{slug}", name=item.name, quantity=item.quantity)


def require_jwt_skeleton(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """Accept JWT-shaped bearer tokens without hardcoding demo secrets.

    This is intentionally a skeleton for demos. A production implementation would validate
    signature, issuer, audience, expiration, and key rotation.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = authorization.removeprefix("Bearer ").strip()
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT skeleton",
        )

    return CurrentUser(username="demo-user", scopes=["read:profile"])


JWT_SKELETON_DEPENDENCY = Depends(require_jwt_skeleton)


@app.get("/auth/me")
def read_current_user(user: CurrentUser = JWT_SKELETON_DEPENDENCY) -> CurrentUser:
    """Return the current user after lightweight JWT-shape validation."""
    return user
