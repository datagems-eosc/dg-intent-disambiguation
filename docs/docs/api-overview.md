# API Overview

The Intent Disambiguation service provides a small RESTful API: one endpoint that
classifies an input, and endpoints for health monitoring. This page describes them; the
full schema is on the [OpenAPI](openapi.md) page, and live documentation is served at
`/swagger` and `/redoc`.

## Authentication

When authentication is enabled (`ENABLE_AUTH=true`, the setting in every deployment),
requests to the intent endpoint must include a token issued by the DataGEMS AAI:

```
Authorization: Bearer <token>
```

See [Security](security.md#authentication) for the checks applied to the token.

## Base URL

```
https://{host}/dg-intent-disambiguation
```

Where `{host}` is the DataGEMS host, for example `datagems-dev.scayle.es` for the
development environment. Inside the cluster the service is reachable at
`http://dg-intent-disambiguation-api-service.athenarc.svc.cluster.local:8000`, without
the path prefix.

## API Endpoints

### Classify an Input

```
POST /api/v1/intent
```

Decides whether the text a user typed asks for datasets or for an answer.

#### Request Headers

| Header | Required | Description |
|---|---|---|
| `Authorization` | when auth is enabled | `Bearer <token>` |
| `Content-Type` | yes | `application/json` |
| `x-tracking-correlation` | no | Correlation id; logged as `DGCorrelationId` and echoed in the response. Generated when missing. |

#### Request Body

```json
{
  "query": "What was the mean temperature in Athens in 2020?",
  "context": {
    "domain": "weather",
    "dataset_ids": ["9b25bc46-8bd3-4f7f-94b4-52dbc38c130f"],
    "history": ["Show me the temperature datasets for Greece"]
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | The text the user typed. 1 to 2000 characters after trimming; any language. |
| `context.domain` | string | no | The topic filter selected on the home page. At most 100 characters. |
| `context.dataset_ids` | array of UUIDs | no | Datasets already selected in the conversation. At most 200. |
| `context.history` | array of strings | no | Earlier user messages, oldest first. At most 10; the last 5 are used. |

#### Response

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

| Field | Type | Description |
|---|---|---|
| `intent` | string | `dataset_search`, `question`, `ambiguous` or `out_of_scope`. See [Intent Classification](intent-classification.md#intents). |
| `confidence` | number | 0 to 1, reported by the model. Labels below the threshold have already been turned into `ambiguous`. |
| `reason` | string | One English sentence explaining the decision. Meant for debugging, not for end users. |
| `search_query` | string or null | English keywords for cross-dataset discovery. `null` only for `out_of_scope`. |
| `degraded` | boolean | `true` when the model could not be used; the answer is then `ambiguous` with the raw input as `search_query`. |
| `model` | string | The model that produced the answer. |
| `prompt_version` | string | The prompt version that produced the answer. |

#### Example

```bash
curl -X POST "https://{host}/dg-intent-disambiguation/api/v1/intent" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-tracking-correlation: 4f9c2a" \
  -d '{"query": "Do you have any data on air pollution in Athens?"}'
```

```json
{
  "intent": "dataset_search",
  "confidence": 1.0,
  "reason": "The user asks whether data on a topic exists, which is a request to find datasets.",
  "search_query": "air pollution Athens",
  "degraded": false,
  "model": "qwen3.8-flash-next",
  "prompt_version": "v1"
}
```

Typical latency is about 1.4 s, and 1.7 s at the 95th percentile. Callers should set a
timeout of about 30 s: the service's own call to SCAYLE times out after 20 s.

### Liveness

```
GET /
```

```json
{"service": "dg-intent-disambiguation", "version": "0.1.0"}
```

### Readiness

```
GET /monitoring/ready
```

```json
{"status": "ready"}
```

Does not depend on SCAYLE. See [Maintenance](maintenance.md#health-checks).

### Health Check

```
GET /monitoring/health-check
```

Reports whether SCAYLE is reachable and the configured model is listed. Always returns
`200` from a live pod; problems show up as `status: degraded`.

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "scayle": {"status": "healthy", "model": "qwen3.8-flash-next", "model_available": true}
}
```
