import ssl
from typing import Any

import jwt
import structlog
from fastapi import HTTPException, Request, Security
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from intent_disambiguation.config import Settings
from intent_disambiguation.logging_setup import logger

bearer = HTTPBearer(auto_error=False)

# Asymmetric algorithms only: a token signed with a shared secret is never accepted.
_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256"]

# Same role policy as the other DataGEMS services (e.g. cross-dataset discovery): end
# users carry "user" or "dg_user"; administrators, curators and system pipelines carry a
# privileged realm role and are accepted too.
USER_ROLES = frozenset({"user", "dg_user"})
PRIVILEGED_ROLES = frozenset({"dg_admin", "dg_system", "dg_dataset-curator"})


class TokenRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TokenVerifier:
    """Validate DataGEMS AAI (Keycloak) access tokens.

    Checks the signature against the realm's published keys, the issuer, the
    expiry and the audience, then that the caller holds a user or privileged realm
    role. Keys are cached for an hour.
    """

    def __init__(
        self,
        issuer: str,
        audience: str | None = None,
        verify_ssl: bool = True,
        jwks_client: jwt.PyJWKClient | None = None,
    ):
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        if jwks_client is None:
            ssl_context = ssl.create_default_context()
            if not verify_ssl:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            jwks_client = jwt.PyJWKClient(
                f"{self._issuer}/protocol/openid-connect/certs",
                cache_keys=True,
                lifespan=3600,
                timeout=10,
                ssl_context=ssl_context,
            )
        self._jwks = jwks_client

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenVerifier":
        return cls(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            verify_ssl=settings.oidc_verify_ssl,
        )

    def verify(self, token: str) -> dict[str, Any]:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as exc:
            logger.error("Cannot fetch the identity provider keys", error=str(exc))
            raise TokenRejected(503, "Cannot verify the token right now") from exc
        except (jwt.PyJWKClientError, jwt.DecodeError) as exc:
            raise TokenRejected(401, "Invalid authentication token") from exc

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                leeway=30,
                options={"require": ["exp", "iss"], "verify_aud": self._audience is not None},
            )
        except jwt.PyJWTError as exc:
            raise TokenRejected(401, "Invalid authentication token") from exc

        roles = set(claims.get("realm_access", {}).get("roles", []))
        if not roles & (USER_ROLES | PRIVILEGED_ROLES):
            logger.warning(
                "Caller missing a required role",
                required_roles=sorted(USER_ROLES | PRIVILEGED_ROLES),
                user_roles=sorted(roles),
                UserId=claims.get("sub"),
                ClientId=claims.get("azp") or claims.get("client_id"),
            )
            raise TokenRejected(403, "Caller does not have a required role")
        return claims


async def require_caller(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer),
) -> dict[str, Any] | None:
    """Return the token claims, or None when ENABLE_AUTH is off."""
    settings: Settings = request.app.state.settings
    if not settings.enable_auth:
        return None
    if credentials is None:
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})

    verifier: TokenVerifier = request.app.state.token_verifier
    try:
        # Fetching keys does blocking I/O on a cache miss
        claims = await run_in_threadpool(verifier.verify, credentials.credentials)
    except TokenRejected as exc:
        logger.warning("Token rejected", reason=exc.detail, status=exc.status_code)
        raise HTTPException(
            exc.status_code, exc.detail, headers={"WWW-Authenticate": "Bearer"}
        ) from exc

    # Same field names as the Gateway's log tracking, so the two can be joined.
    structlog.contextvars.bind_contextvars(
        ClientId=claims.get("azp") or claims.get("client_id"), UserId=claims.get("sub")
    )
    return claims
