import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel

from intent_disambiguation.llm import ScayleError
from intent_disambiguation.logging_setup import logger
from intent_disambiguation.schemas import Intent, IntentContext, IntentResponse

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Strict structured output. "reason" comes first so the model explains itself before
# it commits to a label, which helps when thinking is disabled.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "intent": {"type": "string", "enum": [intent.value for intent in Intent]},
        "confidence": {"type": "number"},
        "search_query": {"type": ["string", "null"]},
    },
    "required": ["reason", "intent", "confidence", "search_query"],
    "additionalProperties": False,
}

FALLBACK_REASON = "The intent model is unavailable, so the user should choose."
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class ChatModel(Protocol):
    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool | None = None,
    ) -> str: ...


class ModelAnswer(BaseModel):
    reason: str = ""
    intent: Intent
    confidence: float
    search_query: str | None = None


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str

    @classmethod
    def load(cls, version: str) -> "PromptTemplate":
        data = yaml.safe_load((PROMPTS_DIR / f"intent_{version}.yaml").read_text("utf-8"))
        examples = "\n".join(_render_example(example) for example in data.get("examples", []))
        system = data["system"].replace("{examples}", examples).strip()
        return cls(version=data.get("version", version), system=system)


def _render_example(example: dict[str, Any]) -> str:
    output = json.dumps(
        {"intent": example["intent"], "search_query": example.get("search_query")},
        ensure_ascii=False,
    )
    line = f'- Input: "{example["query"]}"'
    if example.get("context"):
        line += f" (context: {example['context']})"
    return f"{line}\n  Output: {output}"


def render_user_message(query: str, context: IntentContext | None) -> str:
    lines = ["<input>", query, "</input>"]
    hints: list[str] = []
    if context is not None:
        if context.domain:
            hints.append(f"Topic filter selected by the user: {context.domain}")
        if context.dataset_ids:
            hints.append(
                f"Datasets already selected in this conversation: {len(context.dataset_ids)}"
            )
        if context.history:
            hints.append("Earlier messages in this conversation, oldest first:")
            hints.extend(f"- {message}" for message in context.history[-5:])
    if hints:
        lines += ["<context>", *hints, "</context>"]
    return "\n".join(lines)


def parse_answer(content: str) -> ModelAnswer:
    """Parse the model's JSON, tolerating code fences or text around the object."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(content)
        if match is None:
            raise ValueError(f"no JSON object in model output: {content[:200]!r}") from None
        data = json.loads(match.group(0))
    return ModelAnswer.model_validate(data)


class IntentClassifier:
    def __init__(
        self,
        llm: ChatModel,
        model: str,
        prompt: PromptTemplate,
        *,
        min_confidence: float = 0.6,
        enable_thinking: bool = False,
        max_tokens: int = 1024,
    ):
        self._llm = llm
        self.model = model
        self.prompt = prompt
        self._min_confidence = min_confidence
        self._enable_thinking = enable_thinking
        self._max_tokens = max_tokens

    def build_messages(self, query: str, context: IntentContext | None) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.prompt.system},
            {"role": "user", "content": render_user_message(query, context)},
        ]

    async def classify(self, query: str, context: IntentContext | None = None) -> IntentResponse:
        started = time.perf_counter()
        try:
            content = await self._llm.chat(
                self.model,
                self.build_messages(query, context),
                temperature=0.0,
                max_tokens=self._max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "intent", "schema": RESPONSE_SCHEMA, "strict": True},
                },
                enable_thinking=self._enable_thinking,
            )
            answer = parse_answer(content)
        except (ScayleError, ValueError) as exc:
            logger.warning(
                "Intent model unavailable, falling back to ambiguous",
                error=str(exc),
                latency_ms=_elapsed_ms(started),
            )
            return self._fallback(query)

        response = self._finalize(query, answer)
        logger.info(
            "Intent classified",
            intent=response.intent.value,
            model_intent=answer.intent.value,
            confidence=response.confidence,
            query_length=len(query),
            latency_ms=_elapsed_ms(started),
        )
        logger.debug("Intent input", query=query, search_query=response.search_query)
        return response

    def _finalize(self, query: str, answer: ModelAnswer) -> IntentResponse:
        confidence = min(max(answer.confidence, 0.0), 1.0)
        intent = answer.intent
        # An unsure label is worse than asking the user: the UI handles ambiguous by
        # letting them pick between finding datasets and getting an answer.
        if intent is not Intent.AMBIGUOUS and confidence < self._min_confidence:
            intent = Intent.AMBIGUOUS

        search_query = (answer.search_query or "").strip() or None
        if intent is Intent.OUT_OF_SCOPE:
            search_query = None
        elif search_query is None:
            search_query = query

        return IntentResponse(
            intent=intent,
            confidence=confidence,
            reason=answer.reason.strip(),
            search_query=search_query,
            degraded=False,
            model=self.model,
            prompt_version=self.prompt.version,
        )

    def _fallback(self, query: str) -> IntentResponse:
        return IntentResponse(
            intent=Intent.AMBIGUOUS,
            confidence=0.0,
            reason=FALLBACK_REASON,
            search_query=query,
            degraded=True,
            model=self.model,
            prompt_version=self.prompt.version,
        )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
