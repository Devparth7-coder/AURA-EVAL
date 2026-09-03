from fastapi import APIRouter

from app.api import (
    analytics,
    datasets,
    experiments,
    health,
    internal,
    projects,
    prompts,
    samples,
    sops,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(sops.router)
api_router.include_router(workflows.router)
api_router.include_router(samples.router)
api_router.include_router(datasets.router)
api_router.include_router(analytics.router)
api_router.include_router(experiments.router)
api_router.include_router(prompts.router)
api_router.include_router(internal.router)

__all__ = ["api_router"]
