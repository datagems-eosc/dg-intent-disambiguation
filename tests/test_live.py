"""Smoke test against the real SCAYLE model, using the examples from the kick-off meeting.

Run with `make test-live` (needs the VPN and SCAYLE_* credentials in .env).
The full accuracy measurement is `make eval`.
"""

import os

import pytest

from intent_disambiguation.classifier import IntentClassifier, PromptTemplate
from intent_disambiguation.config import Settings
from intent_disambiguation.llm import ScayleClient

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("SCAYLE_USERNAME"), reason="SCAYLE_* not set"),
]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("What is the temperature in Athens in 2020?", "question"),
        ("Do you have any data about temperatures across Europe?", "dataset_search"),
        ("surface temperature increase", "ambiguous"),
        ("tell me how I feel tonight", "out_of_scope"),
    ],
)
async def test_meeting_examples(query, expected):
    settings = Settings.from_env()
    llm = ScayleClient(
        settings.scayle_base_url,
        settings.scayle_username,
        settings.scayle_password,
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
    try:
        result = await classifier.classify(query)
    finally:
        await llm.aclose()

    assert result.degraded is False
    assert result.intent.value == expected
