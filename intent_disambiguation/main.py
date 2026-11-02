import re
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response

from intent_disambiguation import __version__
from intent_disambiguation.auth import TokenVerifier
from intent_disambiguation.classifier import ChatModel, IntentClassifier, PromptTemplate
from intent_disambiguation.config import Settings, get_settings
from intent_disambiguation.llm import ScayleClient
from intent_disambiguation.logging_setup import logger, setup_logging
from intent_disambiguation.routes import health, intent

# Header the Gateway API uses to correlate a request across DataGEMS services
CORRELATION_HEADER = "x-tracking-correlation"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# Probe endpoints are hit every minute; keep them out of the access log
_QUIET_PATHS = {"/", "/monitoring/ready"}

DESCRIPTION = """
Decides whether text typed into the DataGEMS search box asks for **datasets**
(cross-dataset discovery) or for an **answer** (in-dataset discovery), and returns a
keyword query for the discovery step.
"""


async def correlation_and_access_log(request: Request, call_next) -> Response:
    correlation_id = request.headers.get(CORRELATION_HEADER, "")
    if not _VALID_CORRELATION_ID.match(correlation_id):
        correlation_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(DGCorrelationId=correlation_id)

    started = time.perf_counter()
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = correlation_id
    if request.url.path not in _QUIET_PATHS:
        logger.info(
            "Request handled",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    return response


def create_app(
    settings: Settings | None = None,
    llm: ChatModel | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(json_logs=settings.log_json, log_level=settings.log_level)

    if llm is None:
        llm = ScayleClient(
            base_url=settings.scayle_base_url,
            username=settings.scayle_username,
            password=settings.scayle_password,
            verify_ssl=settings.scayle_verify_ssl,
            timeout=settings.scayle_timeout,
        )
    classifier = IntentClassifier(
        llm,
        settings.intent_model,
        PromptTemplate.load(settings.prompt_version),
        min_confidence=settings.intent_min_confidence,
        enable_thinking=settings.intent_enable_thinking,
        max_tokens=settings.intent_max_tokens,
    )
    if settings.enable_auth and token_verifier is None:
        token_verifier = TokenVerifier.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info(
            "Starting Intent Disambiguation Service",
            version=__version__,
            root_path=settings.base_url,
            model=settings.intent_model,
            thinking=settings.intent_enable_thinking,
            prompt_version=classifier.prompt.version,
            auth=settings.enable_auth,
        )
        yield
        close = getattr(llm, "aclose", None)
        if close is not None:
            await close()

    app = FastAPI(
        title="DataGEMS Intent Disambiguation",
        description=DESCRIPTION,
        version=__version__,
        root_path=settings.base_url,
        openapi_url="/openapi.json",
        docs_url="/swagger",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.llm = llm
    app.state.classifier = classifier
    app.state.token_verifier = token_verifier

    app.middleware("http")(correlation_and_access_log)
    app.include_router(intent.router)
    app.include_router(health.router)

    @app.get("/", tags=["Health"])
    async def read_root() -> dict:
        """Liveness probe."""
        return {"service": "dg-intent-disambiguation", "version": __version__}

    return app


app = create_app()
