from typing import Any

from fastapi import APIRouter, Depends, Request

from intent_disambiguation.auth import require_caller
from intent_disambiguation.classifier import IntentClassifier
from intent_disambiguation.schemas import IntentRequest, IntentResponse

router = APIRouter(prefix="/api/v1", tags=["Intent"])


def get_classifier(request: Request) -> IntentClassifier:
    return request.app.state.classifier


@router.post(
    "/intent",
    response_model=IntentResponse,
    summary="Decide whether the input asks for datasets or for an answer",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "The calling client is not allowed"},
        422: {"description": "Invalid request body"},
        503: {"description": "The identity provider could not be reached"},
    },
)
async def disambiguate_intent(
    body: IntentRequest,
    classifier: IntentClassifier = Depends(get_classifier),
    _caller: dict[str, Any] | None = Depends(require_caller),
) -> IntentResponse:
    """
    Classify the text a user typed into the home-page search box.

    * **dataset_search**: the user wants to find datasets; run cross-dataset discovery.
    * **question**: the user wants an answer; find datasets with cross-dataset discovery,
      then run in-dataset discovery on them.
    * **ambiguous**: both are plausible; ask the user which one they meant.
    * **out_of_scope**: not a data request.

    `search_query` is an English keyword version of the input for cross-dataset
    discovery. When the model is unavailable the service still answers with
    `ambiguous`, `degraded: true` and the raw input as `search_query`, so callers
    can fall back to asking the user.
    """
    return await classifier.classify(body.query, body.context)
