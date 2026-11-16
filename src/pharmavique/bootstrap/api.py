"""FastAPI application factory. Run with: uvicorn pharmavique.bootstrap.api:create_app --factory.

As contexts grow routers (their `presentation/http`), they are mounted here and nowhere else.
"""

from fastapi import FastAPI

from pharmavique.bootstrap import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pharmavique API",
        summary="Drug intelligence platform (SA + EG).",
        description=(
            "Informational only. Nothing returned by this API is medical advice; "
            "the pharmacist or doctor decides."
        ),
    )
    app.include_router(health.router)
    return app
