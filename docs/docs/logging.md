# Logging

This document describes the logging of the Intent Disambiguation service.

## Logging System

The service uses structured logging based on the Python `structlog` library, configured in
`intent_disambiguation/logging_setup.py`. Logs from the service, from uvicorn and from
httpx all go through the same formatter and are written to standard output.

### Log Formats

| `LOG_JSON` | Format | Used in |
|---|---|---|
| `true` | One JSON object per line | Kubernetes |
| `false` | Human-readable, coloured lines | Local development |

### Log Levels

| Level | Description |
|---|---|
| DEBUG | Detailed information, including the user's input and the generated search query |
| INFO | One line per handled request and per classification |
| WARNING | Degraded answers, rejected tokens, disallowed clients |
| ERROR | The AAI signing keys could not be fetched |

The default level is `INFO`, set with `LOG_LEVEL`. httpx request lines are kept at
`WARNING` so that the SCAYLE login is not logged.

## Request Context

Every line written while handling a request carries these fields, using the same names as
the Gateway API's log tracking so that the two can be joined:

| Field | Source |
|---|---|
| `DGCorrelationId` | The `x-tracking-correlation` request header, or a generated UUID when it is missing or invalid. Also returned in the response header. |
| `ClientId` | The token's `azp` (or `client_id`) claim, when authentication is enabled |
| `UserId` | The token's `sub` claim, when authentication is enabled |

## Events

| Event | Level | Fields |
|---|---|---|
| `Starting Intent Disambiguation Service` | INFO | `version`, `root_path`, `model`, `thinking`, `prompt_version`, `auth` |
| `Request handled` | INFO | `method`, `path`, `status`, `latency_ms`. Not written for `/` and `/monitoring/ready`, which the probes call every few seconds. |
| `Intent classified` | INFO | `intent`, `model_intent` (before the confidence threshold), `confidence`, `query_length`, `latency_ms` |
| `Intent input` | DEBUG | `query`, `search_query` |
| `Intent model unavailable, falling back to ambiguous` | WARNING | `error`, `latency_ms` |
| `Token rejected` | WARNING | `reason`, `status` |
| `Client not allowed` | WARNING | `client_id` |
| `Cannot fetch the identity provider keys` | ERROR | `error` |
| `Health check completed` | INFO | `report` |

Example, with `LOG_JSON=true`:

```json
{"intent": "question", "model_intent": "question", "confidence": 1.0, "query_length": 48, "latency_ms": 631, "event": "Intent classified", "DGCorrelationId": "demo-123", "logger": "dg-intent-disambiguation", "level": "info", "timestamp": "2026-10-30T13:26:56.344079Z"}
```

## Privacy

User inputs are not stored. At the default `INFO` level only their length is logged; the
text itself appears only at `DEBUG`. SCAYLE credentials and bearer tokens are never
logged.
