# Configuration

The service is configured entirely through environment variables. For local runs they are
read from a `.env` file (copy `.env.example`); in Kubernetes they come from the
ConfigMap, and the credentials from a Vault-backed Secret (see
[Deployment](deployment.md#kubernetes)).

!!! warning "No quotes in `.env`"

    Do not put quotes around values in `.env`: `docker --env-file` passes them through
    literally, and the SCAYLE login then fails with HTTP 400.

## Environment Variables

### Service

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | empty | Path prefix the service is mounted under behind the ingress, e.g. `/dg-intent-disambiguation`. Used as the FastAPI root path, so `/swagger` works behind the prefix. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |
| `LOG_JSON` | `false` | `true` writes JSON log lines, as in Kubernetes; `false` writes human-readable lines. |

### SCAYLE LLM

| Variable | Default | Description |
|---|---|---|
| `SCAYLE_BASE_URL` | `https://chat.scayle.es/api` | Base URL of the SCAYLE API. The development environment uses `https://172.16.59.5:32443/api`. |
| `SCAYLE_USERNAME` | | LDAP user name. Secret. |
| `SCAYLE_PASSWORD` | | LDAP password. Secret. |
| `SCAYLE_VERIFY_SSL` | `true` | `false` for the development proxy, which uses a self-signed certificate. |
| `SCAYLE_TIMEOUT` | `20` | Read timeout of one LLM call, in seconds. The connect timeout is 5 s. |

### Classification

| Variable | Default | Description |
|---|---|---|
| `INTENT_MODEL` | `qwen3.8-flash-next` | Model id. Ids are case sensitive and get renamed; `/monitoring/health-check` reports whether this one is listed. |
| `INTENT_ENABLE_THINKING` | `false` | Let the model reason before answering. Slower, and reasoning counts against `INTENT_MAX_TOKENS`. |
| `INTENT_MAX_TOKENS` | `1024` | Output token budget per call, including reasoning tokens. |
| `INTENT_MIN_CONFIDENCE` | `0.6` | Labels other than `ambiguous` below this confidence are returned as `ambiguous`. |
| `PROMPT_VERSION` | `v2` | Selects `intent_disambiguation/prompts/intent_<version>.yaml`. |

### Authentication

| Variable | Default | Description |
|---|---|---|
| `ENABLE_AUTH` | `false` | Require a DataGEMS AAI bearer token on the intent endpoint. `true` in every deployment. |
| `OIDC_ISSUER` | `https://datagems-dev.scayle.es/oauth/realms/dev` | Expected token issuer. Signing keys are fetched from `{OIDC_ISSUER}/protocol/openid-connect/certs`. |
| `OIDC_AUDIENCE` | `dg-intent-disambiguation` | The token's `aud` must contain this value. Set it to an empty value to skip the check. |
| `OIDC_VERIFY_SSL` | `true` | Verify the certificate of the AAI when fetching keys. |

## Authentication

With `ENABLE_AUTH=true` the service accepts tokens issued by the realm in `OIDC_ISSUER`
that carry the `OIDC_AUDIENCE` audience and one of the realm roles `user` or `dg_user`, or one of the privileged roles `dg_admin`, `dg_system`, `dg_dataset-curator`. This follows
cross-dataset discovery, which requires the `cross-dataset-discovery-api` audience and the
same roles. The AAI must therefore add the `dg-intent-disambiguation` audience to the
tokens the Gateway exchanges for this service.

See [Security](security.md#authentication) for the full list of checks and the resulting
status codes.

## Development Environment Values

```bash
BASE_URL=/dg-intent-disambiguation
LOG_LEVEL=INFO
LOG_JSON=true
SCAYLE_BASE_URL=https://172.16.59.5:32443/api
SCAYLE_VERIFY_SSL=false
SCAYLE_TIMEOUT=20
INTENT_MODEL=qwen3.8-flash-next
INTENT_ENABLE_THINKING=false
INTENT_MAX_TOKENS=1024
INTENT_MIN_CONFIDENCE=0.6
ENABLE_AUTH=true
OIDC_ISSUER=https://datagems-dev.scayle.es/oauth/realms/dev
OIDC_AUDIENCE=dg-intent-disambiguation
```
