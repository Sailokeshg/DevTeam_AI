"""Small FastAPI demo app for DevTeam AI example runs."""

from fastapi import FastAPI

app = FastAPI(title="DevTeam AI Demo App")


@app.get("/ping")
def ping() -> dict[str, str]:
    """Simple endpoint used by generated test examples."""
    return {"message": "pong"}
