import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from intent_disambiguation.config import Settings
from intent_disambiguation.main import create_app

BASE_SETTINGS = Settings(
    base_url="",
    log_level="WARNING",
    log_json=False,
    scayle_base_url="https://scayle.test/api",
    scayle_username="user",
    scayle_password="secret",
    scayle_verify_ssl=True,
    scayle_timeout=5.0,
    intent_model="test-model",
    intent_enable_thinking=False,
    intent_max_tokens=256,
    intent_min_confidence=0.6,
    prompt_version="v2",
    enable_auth=False,
    oidc_issuer="https://idp.test/oauth/realms/dev",
    oidc_audience=None,
    oidc_verify_ssl=True,
)


def make_settings(**overrides) -> Settings:
    return replace(BASE_SETTINGS, **overrides)


def model_answer(
    intent: str = "question",
    confidence: float = 0.9,
    search_query: str | None = "temperature Athens 2020",
) -> dict:
    return {
        "intent": intent,
        "confidence": confidence,
        "search_query": search_query,
    }


class FakeLLM:
    """Stands in for ScayleClient; records calls and returns a canned reply."""

    def __init__(self, reply: dict | str | None = None, error: Exception | None = None):
        self.reply = model_answer() if reply is None else reply
        self.error = error
        self.models = ["test-model"]
        self.calls: list[dict] = []

    async def chat(self, model, messages, **kwargs) -> str:
        self.calls.append({"model": model, "messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)

    async def list_models(self) -> list[str]:
        if self.error is not None:
            raise self.error
        return self.models


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(fake_llm):
    app = create_app(settings=make_settings(), llm=fake_llm)
    with TestClient(app) as test_client:
        yield test_client
