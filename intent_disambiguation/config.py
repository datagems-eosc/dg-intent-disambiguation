import os
from dataclasses import dataclass
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _env_csv(name: str) -> frozenset[str]:
    return frozenset(item.strip() for item in _env(name).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    base_url: str
    log_level: str
    log_json: bool

    scayle_base_url: str
    scayle_username: str
    scayle_password: str
    scayle_verify_ssl: bool
    scayle_timeout: float

    intent_model: str
    intent_enable_thinking: bool
    intent_max_tokens: int
    intent_min_confidence: float
    prompt_version: str

    enable_auth: bool
    oidc_issuer: str
    oidc_audience: str | None
    allowed_clients: frozenset[str]
    oidc_verify_ssl: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=_env("BASE_URL"),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            log_json=_env_bool("LOG_JSON", False),
            scayle_base_url=_env("SCAYLE_BASE_URL", "https://chat.scayle.es/api"),
            scayle_username=_env("SCAYLE_USERNAME"),
            scayle_password=_env("SCAYLE_PASSWORD"),
            scayle_verify_ssl=_env_bool("SCAYLE_VERIFY_SSL", True),
            scayle_timeout=float(_env("SCAYLE_TIMEOUT", "20")),
            intent_model=_env("INTENT_MODEL", "qwen3.8-flash-next"),
            intent_enable_thinking=_env_bool("INTENT_ENABLE_THINKING", False),
            intent_max_tokens=int(_env("INTENT_MAX_TOKENS", "1024")),
            intent_min_confidence=float(_env("INTENT_MIN_CONFIDENCE", "0.6")),
            prompt_version=_env("PROMPT_VERSION", "v2"),
            enable_auth=_env_bool("ENABLE_AUTH", False),
            oidc_issuer=_env("OIDC_ISSUER", "https://datagems-dev.scayle.es/oauth/realms/dev"),
            oidc_audience=_env("OIDC_AUDIENCE") or None,
            allowed_clients=_env_csv("ALLOWED_CLIENTS"),
            oidc_verify_ssl=_env_bool("OIDC_VERIFY_SSL", True),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
