"""FastAPI application entrypoint for DevTeam AI."""

from fastapi import FastAPI

from app.api.routes import router as api_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(title="DevTeam AI Backend", version="0.1.0")
    application.include_router(api_router)
    return application


app = create_app()
