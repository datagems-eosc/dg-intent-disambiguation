import json

import httpx
import pytest

from intent_disambiguation.llm import ScayleClient, ScayleError

pytestmark = pytest.mark.anyio


def completion(content: str | None, finish_reason: str = "stop") -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


class FakeScayle:
    """In-memory SCAYLE API: LDAP login plus OpenAI-style endpoints."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.logins = 0
        self.chat_statuses: list[int] = []
        self.content: str | None = '{"intent": "question"}'

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/v1/auths/ldap":
            self.logins += 1
            return httpx.Response(200, json={"token": f"token-{self.logins}"})
        if request.url.path == "/api/chat/completions":
            status = self.chat_statuses.pop(0) if self.chat_statuses else 200
            if status != 200:
                return httpx.Response(status, json={"detail": "nope"})
            return httpx.Response(200, json=completion(self.content))
        if request.url.path == "/api/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3"}, {"id": "Qwen3"}]})
        return httpx.Response(404)

    def client(self, **kwargs) -> ScayleClient:
        return ScayleClient(
            "https://scayle.test/api/",
            "user",
            "secret",
            transport=httpx.MockTransport(self.handler),
            **kwargs,
        )


async def test_logs_in_once_and_calls_chat_with_the_token():
    scayle = FakeScayle()
    client = scayle.client()

    first = await client.chat("qwen3", [{"role": "user", "content": "hi"}], enable_thinking=False)
    await client.chat("qwen3", [{"role": "user", "content": "hi"}])

    assert first == '{"intent": "question"}'
    assert scayle.logins == 1
    chat_request = scayle.requests[1]
    assert chat_request.headers["Authorization"] == "Bearer token-1"
    body = json.loads(chat_request.content)
    assert body["model"] == "qwen3"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in json.loads(scayle.requests[2].content)


async def test_renews_the_token_once_on_401():
    scayle = FakeScayle()
    scayle.chat_statuses = [401, 200]

    await scayle.client().chat("qwen3", [])

    assert scayle.logins == 2
    assert scayle.requests[-1].headers["Authorization"] == "Bearer token-2"


async def test_retries_once_on_503():
    scayle = FakeScayle()
    scayle.chat_statuses = [503, 200]

    assert await scayle.client().chat("qwen3", []) == '{"intent": "question"}'


async def test_gives_up_after_the_retry():
    scayle = FakeScayle()
    scayle.chat_statuses = [503, 503]

    with pytest.raises(ScayleError, match="HTTP 503"):
        await scayle.client().chat("qwen3", [])


async def test_empty_completion_raises():
    scayle = FakeScayle()
    scayle.content = None

    with pytest.raises(ScayleError, match="finish_reason=stop"):
        await scayle.client().chat("qwen3", [])


async def test_failed_login_does_not_leak_the_password():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad password secret")

    client = ScayleClient(
        "https://scayle.test/api", "user", "secret", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ScayleError) as excinfo:
        await client.chat("qwen3", [])
    assert "secret" not in str(excinfo.value)


async def test_missing_credentials_raise():
    client = ScayleClient("https://scayle.test/api", "", "", transport=httpx.MockTransport(None))

    with pytest.raises(ScayleError, match="SCAYLE_USERNAME"):
        await client.chat("qwen3", [])


async def test_connection_errors_raise_scayle_error():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("unreachable", request=request)

    client = ScayleClient(
        "https://scayle.test/api", "user", "secret", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ScayleError, match="cannot connect"):
        await client.chat("qwen3", [])
    assert len(attempts) == 2


async def test_lists_models():
    assert await FakeScayle().client().list_models() == ["qwen3", "Qwen3"]
