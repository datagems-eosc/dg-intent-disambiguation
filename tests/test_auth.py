import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from intent_disambiguation.auth import TokenVerifier
from intent_disambiguation.main import create_app

from .conftest import FakeLLM, make_settings

ISSUER = "https://idp.test/oauth/realms/dev"
AUDIENCE = "dg-intent-disambiguation"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKS:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token: str):
        if self.error is not None:
            raise self.error
        return SimpleNamespace(key=PRIVATE_KEY.public_key())


def make_token(**claims) -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": ["account", AUDIENCE],
        "sub": "user-1",
        "azp": "dg-app-api",
        "realm_access": {"roles": ["dg_user", "offline_access"]},
        "iat": now,
        "exp": now + 300,
    }
    payload.update(claims)
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": "k1"})


def make_client(
    jwks: FakeJWKS | None = None, audience: str | None = AUDIENCE, **verifier_kwargs
) -> TestClient:
    verifier = TokenVerifier(
        ISSUER, audience=audience, jwks_client=jwks or FakeJWKS(), **verifier_kwargs
    )
    app = create_app(
        settings=make_settings(enable_auth=True, oidc_issuer=ISSUER),
        llm=FakeLLM(),
        token_verifier=verifier,
    )
    return TestClient(app)


def call(client: TestClient, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/api/v1/intent", json={"query": "q"}, headers=headers)


def test_valid_token_is_accepted():
    assert call(make_client(), make_token()).status_code == 200


def test_missing_token_is_rejected():
    assert call(make_client(), None).status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int(time.time()) - 3600},
        {"iss": "https://evil.test/realms/dev"},
    ],
    ids=["expired", "wrong-issuer"],
)
def test_invalid_claims_are_rejected(claims):
    assert call(make_client(), make_token(**claims)).status_code == 401


def test_symmetric_token_is_rejected():
    token = jwt.encode({"iss": ISSUER, "exp": int(time.time()) + 300}, "x" * 32, algorithm="HS256")

    assert call(make_client(), token).status_code == 401


def test_garbage_token_is_rejected():
    client = make_client(FakeJWKS(error=jwt.DecodeError("bad")))

    assert call(client, "not-a-jwt").status_code == 401


@pytest.mark.parametrize("role", ["user", "dg_user", "dg_admin", "dg_system", "dg_dataset-curator"])
def test_user_and_privileged_roles_are_accepted(role):
    token = make_token(realm_access={"roles": [role]})

    assert call(make_client(), token).status_code == 200


@pytest.mark.parametrize(
    "claims",
    [{"realm_access": {"roles": ["offline_access"]}}, {"realm_access": {}}],
    ids=["other-roles", "no-roles"],
)
def test_token_without_a_required_role_is_forbidden(claims):
    assert call(make_client(), make_token(**claims)).status_code == 403


def test_token_for_another_audience_is_rejected():
    assert call(make_client(), make_token(aud="cross-dataset-discovery-api")).status_code == 401
    assert call(make_client(), make_token(aud=None)).status_code == 401


def test_audience_check_can_be_disabled():
    client = make_client(audience=None)

    assert call(client, make_token(aud="account")).status_code == 200


def test_unreachable_identity_provider_returns_503():
    client = make_client(FakeJWKS(error=jwt.PyJWKClientConnectionError("down")))

    assert call(client, make_token()).status_code == 503


def test_probes_do_not_need_a_token():
    client = make_client()

    assert client.get("/").status_code == 200
    assert client.get("/monitoring/ready").status_code == 200
    assert client.get("/monitoring/health-check").status_code == 200
