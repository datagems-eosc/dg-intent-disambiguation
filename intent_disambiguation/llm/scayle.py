import asyncio
from typing import Any

import httpx

# Statuses worth one more try: the SCAYLE proxy or the model server restarting.
_RETRY_STATUSES = {502, 503, 504}


class ScayleError(Exception):
    """The SCAYLE API could not be reached or returned an unusable answer."""


class ScayleClient:
    """Async client for the OpenAI-compatible SCAYLE LLM API.

    Authentication exchanges LDAP credentials for a bearer token
    (``POST /v1/auths/ldap``). The token is cached and renewed once when a call
    returns 401. Credentials are never logged or put in exception messages.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: float = 20.0,
        connect_timeout: float = 5.0,
        retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        # httpx appends request paths to the base path only when it ends with "/"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            verify=verify_ssl,
            timeout=httpx.Timeout(timeout, connect=min(connect_timeout, timeout)),
            transport=transport,
        )
        self._username = username
        self._password = password
        self._retries = retries
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _authenticate(self, stale_token: str | None = None) -> str:
        async with self._auth_lock:
            # Another request may have renewed the token while this one waited.
            if self._token is not None and self._token != stale_token:
                return self._token
            if not self._username or not self._password:
                raise ScayleError("SCAYLE_USERNAME / SCAYLE_PASSWORD are not set")
            response = await self._send(
                "POST", "v1/auths/ldap", json={"user": self._username, "password": self._password}
            )
            if response.status_code != 200:
                raise ScayleError(f"authentication failed with HTTP {response.status_code}")
            token = response.json().get("token")
            if not token:
                raise ScayleError("authentication succeeded but returned no token")
            self._token = token
            return token

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self._retries + 1):
            last_attempt = attempt == self._retries
            try:
                response = await self._client.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if last_attempt:
                    raise ScayleError(f"{method} {path}: cannot connect ({exc!r})") from exc
                continue
            except httpx.HTTPError as exc:
                raise ScayleError(f"{method} {path}: {exc!r}") from exc
            if response.status_code in _RETRY_STATUSES and not last_attempt:
                continue
            return response
        raise AssertionError("unreachable")

    async def _authorized(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._authenticate()
        response = await self._send(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        if response.status_code == 401:
            token = await self._authenticate(stale_token=token)
            response = await self._send(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        if response.status_code != 200:
            raise ScayleError(
                f"{method} {path} -> HTTP {response.status_code}: {response.text[:300]}"
            )
        return response

    async def list_models(self) -> list[str]:
        response = await self._authorized("GET", "models")
        entries = response.json().get("data", [])
        return [entry["id"] for entry in entries if isinstance(entry, dict) and "id" in entry]

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool | None = None,
    ) -> str:
        """Run one chat completion and return the answer text.

        ``enable_thinking=False`` asks Qwen-style models to skip their reasoning
        phase. Reasoning tokens count against ``max_tokens``; a reply cut off
        while still reasoning has no content and raises ``ScayleError``.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            body["response_format"] = response_format
        if enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": enable_thinking}

        response = await self._authorized("POST", "chat/completions", json=body)
        try:
            choice = response.json()["choices"][0]
            content = choice["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ScayleError(f"unexpected completion payload: {response.text[:300]}") from exc
        if not content or not content.strip():
            raise ScayleError(f"empty completion (finish_reason={choice.get('finish_reason')})")
        return content
