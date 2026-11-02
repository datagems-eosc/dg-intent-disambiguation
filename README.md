# dg-intent-disambiguation

Intent disambiguation service of the DataGEMS platform.

It reads what a user typed into the search box and decides which flow should handle
it:

| Intent | Meaning | What the platform does |
|---|---|---|
| `dataset_search` | The user wants to find datasets | Cross-dataset discovery |
| `question` | The user wants an answer from data | Cross-dataset discovery to pick datasets, then in-dataset discovery |
| `ambiguous` | Either is plausible | Ask the user which one they meant |
| `out_of_scope` | Not a data request | Show a message and example queries |

It also returns `search_query`, an English keyword version of the input for the
cross-dataset discovery step.

The service only classifies. It does not call other DataGEMS components; the Gateway
API runs the chosen flow. It is separate from the Gateway's existing
`/api/search/disambiguate-query`, which rewrites unclear terms inside a query.

**Documentation:** <https://datagems-eosc.github.io/dg-intent-disambiguation/> (sources in
[docs/](docs/)). The [Integration Guide](docs/docs/integration.md) has the API contract
and how the Gateway and the UI are expected to use it.

## How it works

One call to an LLM on SCAYLE (`qwen3.8-flash-next` by default) with a versioned prompt
([intent_disambiguation/prompts/intent_v2.yaml](intent_disambiguation/prompts/intent_v2.yaml))
and strict JSON-schema output. A label with confidence below `INTENT_MIN_CONFIDENCE`
becomes `ambiguous`. If SCAYLE fails, the endpoint still answers `ambiguous` with
`degraded: true`, so the home page keeps working and the user is asked to choose.

## Run locally

Needs [uv](https://docs.astral.sh/uv/) and the SCAYLE dev VPN.

```bash
make install
cp .env.example .env      # fill in SCAYLE_USERNAME / SCAYLE_PASSWORD, no quotes
make run                  # http://localhost:8000/swagger
```

```bash
curl -s localhost:8000/api/v1/intent \
  -H 'Content-Type: application/json' \
  -d '{"query": "What was the mean temperature in Athens in 2020?"}'
```

## Tests and evaluation

| Command | What it does |
|---|---|
| `make test` | Unit tests with a fake LLM; no network needed, runs in CI |
| `make test-live` | The kick-off meeting's examples against the real model |
| `make eval` | Accuracy on [eval/queries.yaml](eval/queries.yaml) against the real model |
| `make benchmark` | Accuracy on the 876-input [benchmark](eval/benchmark/) (about 5 minutes) |

`make eval` prints accuracy, per-intent precision and recall, a confusion table,
**misroutes** (a dataset search sent to the question flow or the other way round, or a
data request marked out of scope) and latency. It saves every answer to `eval/results/`.
`--thinking`, `--model`, `--prompt-version` and `--min-confidence` override the
settings, and `--url ... --token ...` evaluates a deployed instance.

Results on 30 Oct 2026 (134 inputs; English, Greek, French, German, Spanish; including
follow-ups with context):

| Setting | Accuracy | Misroutes | Latency p50 / p95 |
|---|---|---|---|
| thinking off (default) | 100% | 0 | 1.1 s / 1.25 s |
| thinking on | 100% | 0 | 1.6 s / 2.35 s |

The set was written alongside the prompt, so treat it as a regression check rather
than an independent benchmark. Add real user inputs to it as they come in, especially
any that were routed wrongly.

The independent measurement is the **benchmark** in [eval/benchmark/](eval/benchmark/):
876 inputs written and labelled by other model families (DeepSeek and GLM), reviewed by
hand, in 10 languages, with noise, follow-ups and contested cases. On it the deployed
configuration scores 96.5% strict accuracy with 2 misroutes in 679 inputs. Run it with
`make benchmark`. See the [benchmark README](eval/benchmark/README.md) for the method, the
results and the error patterns.

To change the prompt, add `prompts/intent_v2.yaml`, run
`uv run --env-file .env python eval/run_eval.py --prompt-version v3`, compare it with v2,
and then set `PROMPT_VERSION`. Keep the prompt's examples out of the evaluation set.

## Configuration

All settings are environment variables; see [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `BASE_URL` | empty | Path prefix behind the ingress (`/dg-intent-disambiguation`) |
| `LOG_LEVEL`, `LOG_JSON` | `INFO`, `false` | JSON logs in Kubernetes |
| `SCAYLE_BASE_URL` | `https://chat.scayle.es/api` | Dev: `https://172.16.59.5:32443/api` |
| `SCAYLE_USERNAME`, `SCAYLE_PASSWORD` | | From the Vault secret in Kubernetes |
| `SCAYLE_VERIFY_SSL` | `true` | `false` for the dev proxy |
| `SCAYLE_TIMEOUT` | `20` | Read timeout per LLM call, seconds |
| `INTENT_MODEL` | `qwen3.8-flash-next` | Model ids are case sensitive and get renamed |
| `INTENT_ENABLE_THINKING` | `false` | Reasoning before answering; slower |
| `INTENT_MAX_TOKENS` | `1024` | Includes reasoning tokens when thinking is on |
| `INTENT_MIN_CONFIDENCE` | `0.6` | Lower confidence becomes `ambiguous` |
| `PROMPT_VERSION` | `v2` | Selects `prompts/intent_<version>.yaml` |
| `ENABLE_AUTH` | `false` | Require a DataGEMS AAI bearer token |
| `OIDC_ISSUER` | dev realm | Token issuer; keys come from its JWKS endpoint |
| `OIDC_AUDIENCE` | empty | Required `aud` value, if set |
| `ALLOWED_CLIENTS` | empty | Comma-separated client ids (`azp`) allowed to call |

Logs are structured (structlog). Each request carries the Gateway's
`x-tracking-correlation` header as `DGCorrelationId`, and the caller as `ClientId` and
`UserId`, the same names the Gateway uses. Input text is logged only at `DEBUG`.

## Endpoints

| Method | Path | |
|---|---|---|
| POST | `/api/v1/intent` | Classify an input |
| GET | `/` | Liveness |
| GET | `/monitoring/ready` | Readiness; does not depend on SCAYLE |
| GET | `/monitoring/health-check` | SCAYLE reachability and model availability; always 200 |
| GET | `/swagger`, `/redoc`, `/openapi.json` | API docs |

## Release

1. Bump `version` in `pyproject.toml` and `intent_disambiguation/__init__.py`.
2. Tag `vX.Y.Z` and push the tag. GitHub Actions publishes
   `ghcr.io/datagems-eosc/dg-intent-disambiguation:vX.Y.Z`.
3. Update the image tag in `dg-intent-disambiguation-deployment-dev` (then `-prod`) and
   run its deploy script.
4. Run the **Deploy Docs (On-Demand)** workflow with the version, e.g. `0.2.0`. It
   publishes the site to GitHub Pages with `mike` and points `latest` at it.

## Documentation

The docs site is built with MkDocs Material, like the other DataGEMS services.

```bash
make docs           # serve locally at http://127.0.0.1:8000
make docs-test      # strict build, fails on broken links or warnings
make docs-openapi   # refresh docs/docs/content/openapi.json after changing the API
```

`tests/test_openapi_doc.py` fails when the published OpenAPI document no longer matches
the code.

## GitHub Actions

| Workflow | Trigger | |
|---|---|---|
| Tests | push to `main`, pull requests | lint and unit tests |
| Build and Push Intent Disambiguation Image | `v*` tag | publishes the Docker image |
| Deploy Docs (On-Demand) | manual, with a version | publishes the docs site |
| CodeQL Scan (On-Demand) | manual | static analysis of Python and workflow files |
| Vulnerability Scan (On-Demand) | manual, with an image tag | Trivy scan of the Dockerfile and image |
| Code Metrics (On-Demand) | manual | radon maintainability, complexity and size report |

## Layout

```
intent_disambiguation/
  main.py          app factory, correlation id and access log middleware
  classifier.py    prompt rendering, LLM call, parsing, confidence threshold, fallback
  llm/scayle.py    SCAYLE client: LDAP token, renewal on 401, one retry
  auth.py          AAI token validation (JWKS, issuer, expiry, audience, client)
  schemas.py       request and response models
  prompts/         versioned prompts
  routes/          intent and health endpoints
eval/              labelled inputs, the benchmark and the evaluation script
docs/              documentation site (MkDocs)
scripts/           OpenAPI export for the docs
tests/             unit tests; test_live.py needs the VPN
```
