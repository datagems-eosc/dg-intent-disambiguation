# Status & Error Codes

This page documents the status codes returned by the Intent Disambiguation API and how
failures of the underlying LLM are reported.

## HTTP Status Codes

| Status Code | Description |
|---|---|
| 200 | OK. The input was classified. Also returned when the LLM failed: see [Degraded Answers](#degraded-answers). |
| 401 | Unauthorized. Authentication is enabled and the token is missing, expired, wrongly signed, or has the wrong issuer or audience. |
| 403 | Forbidden. The token is valid but its client (`azp`) is not in `ALLOWED_CLIENTS`. |
| 422 | Unprocessable Entity. The request body failed validation: missing or blank `query`, `query` longer than 2000 characters, too many `history` items or `dataset_ids`, or a `dataset_ids` entry that is not a UUID. |
| 500 | Internal Server Error. An unexpected error occurred in the service. |
| 503 | Service Unavailable. The AAI signing keys could not be fetched, so the token could not be checked. Retry shortly. |

!!! note "Validation errors"

    Request validation is handled by FastAPI and pydantic and returns `422` with a list
    of the offending fields:

    ```json
    {
      "detail": [
        {
          "type": "value_error",
          "loc": ["body", "query"],
          "msg": "Value error, query must not be blank",
          "input": "   "
        }
      ]
    }
    ```

## Degraded Answers

The intent endpoint never turns an LLM problem into an error status. When the SCAYLE API
cannot be reached, times out, rejects the request, or returns an empty or invalid answer,
the response is `200` with:

| Field | Value |
|---|---|
| `intent` | `ambiguous` |
| `confidence` | `0.0` |
| `degraded` | `true` |
| `search_query` | the raw input |

Callers handle it like any `ambiguous` answer: ask the user whether they want datasets or
an answer. The cause is logged as a warning (`Intent model unavailable, falling back to
ambiguous`), and `/monitoring/health-check` shows whether SCAYLE is reachable.

## Health Status Values

| Value | Endpoint | Meaning |
|---|---|---|
| `ready` | `/monitoring/ready` | The process serves requests. |
| `healthy` | `/monitoring/health-check` | SCAYLE is reachable and the configured model is listed. |
| `degraded` | `/monitoring/health-check` | SCAYLE is unreachable, or the configured model is not listed (model ids are case sensitive and get renamed). The `scayle.message` field explains which. |
