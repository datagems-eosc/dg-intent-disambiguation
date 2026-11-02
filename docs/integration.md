# Integrating intent disambiguation

For the Gateway API and the UI. The service answers one question about what a user
typed into the home-page search box: do they want **datasets** or an **answer**?

## Endpoint

```
POST {base}/api/v1/intent
```

| Environment | `{base}` |
|---|---|
| Dev, in cluster | `http://dg-intent-disambiguation-api-service.athenarc.svc.cluster.local:8000` |
| Dev, public | `https://datagems-dev.scayle.es/dg-intent-disambiguation` |

Swagger: `https://datagems-dev.scayle.es/dg-intent-disambiguation/swagger`

### Headers

| Header | |
|---|---|
| `Authorization: Bearer <token>` | Token issued by the DataGEMS AAI (dev realm). The exchanged token the Gateway uses for other services works. |
| `x-tracking-correlation` | Optional. Logged as `DGCorrelationId` and echoed back. |

### Request

```json
{
  "query": "What was the mean temperature in Athens in 2020?",
  "context": {
    "domain": "weather",
    "dataset_ids": ["9b25bc46-8bd3-4f7f-94b4-52dbc38c130f"],
    "history": ["Earlier user message"]
  }
}
```

- `query`: required, 1 to 2000 characters, any language.
- `context`: optional; every field is optional. It is passed to the model as a hint:
  - `domain`: the topic filter the user picked on the home page, if any.
  - `dataset_ids`: datasets already selected in the conversation. With datasets
    selected, short follow-ups ("and per month?") are read as questions about them.
  - `history`: earlier user messages, oldest first; the last 5 are used.

### Response

```json
{
  "intent": "question",
  "confidence": 0.95,
  "reason": "Asks for a computed value for a specific place and year.",
  "search_query": "mean temperature Athens 2020",
  "degraded": false,
  "model": "qwen3.8-flash-next",
  "prompt_version": "v1"
}
```

| Field | |
|---|---|
| `intent` | `dataset_search`, `question`, `ambiguous` or `out_of_scope` |
| `confidence` | 0 to 1, reported by the model. Labels below 0.6 are already turned into `ambiguous`. |
| `reason` | One English sentence. Useful for debugging; not meant for end users. |
| `search_query` | English keywords for cross-dataset discovery. `null` only for `out_of_scope`. |
| `degraded` | `true` when the model could not be reached. The answer is then `ambiguous` with the raw input as `search_query`. |
| `model`, `prompt_version` | What produced the answer, for logs and comparisons. |

### Status codes

| Code | When |
|---|---|
| 200 | Always when the request is valid, including when the model is down (`degraded: true`) |
| 401 | Missing, expired or invalid token |
| 403 | The calling client is not on the allow list |
| 422 | Invalid body (blank or overlong query, malformed `dataset_ids`) |
| 503 | The AAI keys could not be fetched to check the token |

Latency is about 1.1 s typical and 1.3 s at p95. Set a client timeout of about 30 s:
the service's own call to SCAYLE times out after 20 s.

## Suggested routing

| Intent | Gateway | UI |
|---|---|---|
| `dataset_search` | Run cross-dataset discovery with `search_query` | Datasets page, smart search box filled with the user's text, results below |
| `question` | Run cross-dataset discovery with `search_query`, take the top datasets, then run in-dataset discovery with the **original** `query` on them | Chat with those datasets pre-selected and the answer. Offer "show me the datasets instead" |
| `ambiguous` | Nothing yet | Ask: "Find datasets about this" or "Get an answer". Then follow the chosen row above |
| `out_of_scope` | Nothing | A short message and the example queries |

Notes:

- `search_query` is for retrieval only. Show the user their own text, and give
  in-dataset discovery the original question: keywords drop words that matter for
  answering ("mean", "per month").
- The UI should always let the user switch between the dataset and answer flows,
  because the model can be wrong.
- `question` depends on in-dataset discovery accepting dataset ids. Today the Gateway's
  `in-data-explore` call forwards only the question.

## Suggested Gateway configuration

Following the existing `service-*.json` files:

```json
{
  "IntentDisambiguationService": {
    "Scope": "datagems",
    "BaseUrl": "%{IntentDisambiguationBaseUrl}%",
    "IntentEndpoint": "api/v1/intent"
  }
}
```

The service validates the token's signature, issuer and expiry. It does not yet
require a specific audience or client. Once the Gateway's first calls show its client
id in the logs, `ALLOWED_CLIENTS` will be set to it (expected `dg-app-api`). Tell us if
the exchanged token for this scope should carry a specific `aud` value.
