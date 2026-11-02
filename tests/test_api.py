import uuid

from intent_disambiguation.llm import ScayleError
from intent_disambiguation.main import CORRELATION_HEADER
from intent_disambiguation.schemas import MAX_QUERY_LENGTH

from .conftest import model_answer


def test_returns_the_model_answer(client):
    response = client.post("/api/v1/intent", json={"query": "Mean temperature in Athens 2020?"})

    assert response.status_code == 200
    assert response.json() == {
        "intent": "question",
        "confidence": 0.9,
        "reason": "Asks for a value.",
        "search_query": "temperature Athens 2020",
        "degraded": False,
        "model": "test-model",
        "prompt_version": "v1",
    }


def test_query_is_stripped_before_classification(client, fake_llm):
    client.post("/api/v1/intent", json={"query": "  air quality Greece \n"})

    user_message = fake_llm.calls[0]["messages"][1]["content"]
    assert "<input>\nair quality Greece\n</input>" in user_message


def test_blank_query_is_rejected(client, fake_llm):
    response = client.post("/api/v1/intent", json={"query": "   "})

    assert response.status_code == 422
    assert fake_llm.calls == []


def test_overlong_query_is_rejected(client):
    response = client.post("/api/v1/intent", json={"query": "a" * (MAX_QUERY_LENGTH + 1)})

    assert response.status_code == 422


def test_missing_query_is_rejected(client):
    assert client.post("/api/v1/intent", json={}).status_code == 422


def test_context_is_passed_to_the_model_as_hints(client, fake_llm):
    client.post(
        "/api/v1/intent",
        json={
            "query": "and per month?",
            "context": {
                "domain": "weather",
                "dataset_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                "history": ["What was the mean temperature in Athens in 2020?"],
            },
        },
    )

    user_message = fake_llm.calls[0]["messages"][1]["content"]
    assert "Topic filter selected by the user: weather" in user_message
    assert "Datasets already selected in this conversation: 2" in user_message
    assert "- What was the mean temperature in Athens in 2020?" in user_message


def test_invalid_dataset_id_in_context_is_rejected(client):
    response = client.post(
        "/api/v1/intent", json={"query": "q", "context": {"dataset_ids": ["not-a-uuid"]}}
    )

    assert response.status_code == 422


def test_model_failure_degrades_to_ambiguous(client, fake_llm):
    fake_llm.error = ScayleError("connection refused")

    response = client.post("/api/v1/intent", json={"query": "rainfall in Crete"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "ambiguous"
    assert body["degraded"] is True
    assert body["confidence"] == 0.0
    assert body["search_query"] == "rainfall in Crete"


def test_out_of_scope_has_no_search_query(client, fake_llm):
    fake_llm.reply = model_answer(intent="out_of_scope", confidence=0.99, search_query="feelings")

    body = client.post("/api/v1/intent", json={"query": "how do I feel?"}).json()

    assert body["intent"] == "out_of_scope"
    assert body["search_query"] is None


def test_correlation_id_is_echoed(client):
    response = client.post(
        "/api/v1/intent", json={"query": "q"}, headers={CORRELATION_HEADER: "abc-123"}
    )

    assert response.headers[CORRELATION_HEADER] == "abc-123"


def test_correlation_id_is_generated_when_missing_or_invalid(client):
    missing = client.get("/monitoring/ready").headers[CORRELATION_HEADER]
    invalid = client.get("/monitoring/ready", headers={CORRELATION_HEADER: "bad\nvalue"}).headers[
        CORRELATION_HEADER
    ]

    assert uuid.UUID(missing)
    assert uuid.UUID(invalid)


def test_liveness_and_readiness(client):
    assert client.get("/").json()["service"] == "dg-intent-disambiguation"
    assert client.get("/monitoring/ready").json() == {"status": "ready"}


def test_health_check_reports_healthy(client):
    body = client.get("/monitoring/health-check").json()

    assert body["status"] == "healthy"
    assert body["scayle"]["model_available"] is True


def test_health_check_reports_missing_model(client, fake_llm):
    fake_llm.models = ["other-model"]

    response = client.get("/monitoring/health-check")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["scayle"]["model_available"] is False


def test_health_check_reports_unreachable_scayle(client, fake_llm):
    fake_llm.error = ScayleError("cannot connect")

    response = client.get("/monitoring/health-check")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert "cannot connect" in response.json()["scayle"]["message"]


def test_openapi_and_swagger_are_served(client):
    spec = client.get("/openapi.json").json()

    assert "/api/v1/intent" in spec["paths"]
    assert client.get("/swagger").status_code == 200
