import pytest

from intent_disambiguation.classifier import (
    RESPONSE_SCHEMA,
    IntentClassifier,
    PromptTemplate,
    parse_answer,
)
from intent_disambiguation.llm import ScayleError
from intent_disambiguation.schemas import Intent

from .conftest import FakeLLM, model_answer

pytestmark = pytest.mark.anyio


def make_classifier(llm: FakeLLM, **kwargs) -> IntentClassifier:
    return IntentClassifier(llm, "test-model", PromptTemplate.load("v2"), **kwargs)


def test_prompt_renders_the_examples():
    prompt = PromptTemplate.load("v2")

    assert prompt.version == "v2"
    assert "reason" not in RESPONSE_SCHEMA["properties"]
    assert "{examples}" not in prompt.system
    assert '- Input: "write a haiku about rain"' in prompt.system
    assert '"intent": "out_of_scope", "search_query": null' in prompt.system


async def test_sends_strict_schema_and_thinking_flag():
    llm = FakeLLM()

    await make_classifier(llm, enable_thinking=False, max_tokens=300).classify("q")

    call = llm.calls[0]
    assert call["response_format"]["json_schema"]["schema"] == RESPONSE_SCHEMA
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["enable_thinking"] is False
    assert call["max_tokens"] == 300
    assert call["temperature"] == 0.0


@pytest.mark.parametrize("intent", ["dataset_search", "question", "out_of_scope"])
async def test_low_confidence_becomes_ambiguous(intent):
    llm = FakeLLM(model_answer(intent=intent, confidence=0.4, search_query="kw"))

    result = await make_classifier(llm, min_confidence=0.6).classify("q")

    assert result.intent is Intent.AMBIGUOUS
    assert result.confidence == 0.4
    assert result.search_query == "kw"


async def test_confidence_at_threshold_is_kept():
    llm = FakeLLM(model_answer(intent="dataset_search", confidence=0.6))

    result = await make_classifier(llm, min_confidence=0.6).classify("q")

    assert result.intent is Intent.DATASET_SEARCH


async def test_confidence_is_clamped():
    llm = FakeLLM(model_answer(confidence=1.7))

    assert (await make_classifier(llm).classify("q")).confidence == 1.0


async def test_blank_search_query_falls_back_to_the_input():
    llm = FakeLLM(model_answer(intent="dataset_search", search_query="  "))

    result = await make_classifier(llm).classify("air quality Greece")

    assert result.search_query == "air quality Greece"


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        '{"intent": "maybe", "confidence": 0.9, "search_query": null}',
        '{"intent": "question"}',
    ],
)
async def test_unusable_model_output_degrades(reply):
    result = await make_classifier(FakeLLM(reply)).classify("rainfall in Crete")

    assert result.degraded is True
    assert result.intent is Intent.AMBIGUOUS
    assert result.search_query == "rainfall in Crete"


async def test_scayle_error_degrades():
    result = await make_classifier(FakeLLM(error=ScayleError("timeout"))).classify("q")

    assert result.degraded is True


def test_parse_answer_accepts_fenced_json():
    content = '```json\n{"intent": "question", "confidence": 0.8, "search_query": "x"}\n```'

    assert parse_answer(content).intent is Intent.QUESTION
