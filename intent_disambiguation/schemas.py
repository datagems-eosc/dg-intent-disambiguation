from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUERY_LENGTH = 2000


class Intent(StrEnum):
    DATASET_SEARCH = "dataset_search"
    QUESTION = "question"
    AMBIGUOUS = "ambiguous"
    OUT_OF_SCOPE = "out_of_scope"


class IntentContext(BaseModel):
    """Optional hints about where the input was typed. Used as hints only."""

    model_config = ConfigDict(extra="ignore")

    domain: str | None = Field(
        default=None,
        max_length=100,
        description="Topic filter selected on the home page, e.g. 'weather'.",
    )
    dataset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=200,
        description="Datasets already selected in the conversation.",
    )
    history: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Previous user messages of the conversation, oldest first.",
    )

    @field_validator("history")
    @classmethod
    def _trim_history(cls, value: list[str]) -> list[str]:
        return [item.strip()[:MAX_QUERY_LENGTH] for item in value if item and item.strip()]


class IntentRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"query": "What was the mean temperature in Athens in 2020?"},
                {
                    "query": "and per month?",
                    "context": {
                        "dataset_ids": ["9b25bc46-8bd3-4f7f-94b4-52dbc38c130f"],
                        "history": ["What was the mean temperature in Athens in 2020?"],
                    },
                },
            ]
        }
    )

    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="The text the user typed.",
    )
    context: IntentContext | None = None

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class IntentResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "intent": "question",
                    "confidence": 0.95,
                    "search_query": "air temperature Athens 2020",
                    "degraded": False,
                    "model": "qwen3.8-flash-next",
                    "prompt_version": "v2",
                }
            ]
        }
    )

    intent: Intent = Field(
        description=(
            "dataset_search: the user wants to find datasets. "
            "question: the user wants an answer computed from data. "
            "ambiguous: either is plausible; ask the user. "
            "out_of_scope: not a data request."
        )
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Self-reported by the model.")
    search_query: str | None = Field(
        description=(
            "English keyword query for cross-dataset discovery. "
            "Null when the intent is out_of_scope."
        )
    )
    degraded: bool = Field(
        description=(
            "True when the model could not be used and the service fell back to "
            "'ambiguous' with the raw input as search_query."
        )
    )
    model: str
    prompt_version: str
