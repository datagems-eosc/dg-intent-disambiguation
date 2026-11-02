import asyncio

from fastapi import APIRouter, Request

from intent_disambiguation import __version__
from intent_disambiguation.llm import ScayleError
from intent_disambiguation.logging_setup import logger

router = APIRouter(prefix="/monitoring", tags=["Health"])

HEALTH_CHECK_TIMEOUT = 10.0


@router.get("/ready")
async def readiness() -> dict:
    """Readiness probe. Does not depend on SCAYLE: an LLM outage must not take the pod
    out of the Service, because the intent endpoint degrades gracefully."""
    return {"status": "ready"}


@router.get("/health-check")
async def check_health(request: Request) -> dict:
    """
    Report whether SCAYLE is reachable and the configured model is listed.

    Always returns HTTP 200 from a live pod; a problem shows up as `status: degraded`.

    ```json
    {
        "status": "healthy",
        "version": "0.2.0",
        "scayle": {"status": "healthy", "model": "qwen3.8-flash-next", "model_available": true}
    }
    ```
    """
    model = request.app.state.settings.intent_model
    scayle = {"status": "healthy", "model": model, "model_available": True}
    try:
        models = await asyncio.wait_for(
            request.app.state.llm.list_models(), timeout=HEALTH_CHECK_TIMEOUT
        )
        if model not in models:
            scayle.update(
                status="degraded",
                model_available=False,
                message=f"Model {model!r} is not listed (ids are case sensitive)",
            )
    except (ScayleError, TimeoutError) as exc:
        scayle.update(
            status="degraded", model_available=False, message=f"SCAYLE unreachable: {exc!r}"
        )

    report = {"status": scayle["status"], "version": __version__, "scayle": scayle}
    logger.info("Health check completed", report=report)
    return report
