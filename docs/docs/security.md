# Security

This page summarizes the security-relevant aspects of the Intent Disambiguation service.

## Authentication

The intent endpoint accepts bearer tokens issued by the
[DataGEMS AAI](https://datagems-eosc.github.io/dg-aai) (Keycloak). Authentication is
switched on with `ENABLE_AUTH=true`, which is the setting in every deployment; with
`ENABLE_AUTH=false` (the default for local runs) the endpoint is open.

When enabled, each request to `POST /api/v1/intent` must carry:

```
Authorization: Bearer <token>
```

The token is accepted only if all of these checks pass:

| Check | Detail |
|---|---|
| Signature | Verified against the realm's published keys (`{OIDC_ISSUER}/protocol/openid-connect/certs`), cached for one hour. Only asymmetric algorithms are accepted (RS256, RS384, RS512, PS256, ES256); a token signed with a shared secret is rejected. |
| Issuer | `iss` must equal `OIDC_ISSUER`. |
| Expiry | `exp` is required and checked, with 30 seconds of leeway. |
| Audience | `aud` must contain `OIDC_AUDIENCE` (default `dg-intent-disambiguation`). An empty value skips this check. |
| Role | The token's realm roles (`realm_access.roles`) must include `user` or `dg_user`, or one of the privileged roles `dg_admin`, `dg_system`, `dg_dataset-curator`. |

These are the same checks cross-dataset discovery applies, with this service's own
audience in place of `cross-dataset-discovery-api`. The Gateway API calls the service with
the token-exchange flow, as it does for other DataGEMS services, so the token represents
the original user; the AAI adds the `dg-intent-disambiguation` audience to it.

| Outcome | Status |
|---|---|
| Missing token, bad signature, wrong issuer or audience, expired | `401 Unauthorized` |
| Valid token without a user or privileged realm role | `403 Forbidden` |
| Signing keys cannot be fetched from the AAI | `503 Service Unavailable` |

The health and documentation endpoints (`/`, `/monitoring/*`, `/swagger`, `/redoc`,
`/openapi.json`) do not require a token.

## Transport

The service is deployed behind the DataGEMS ingress, which terminates TLS. Inside the
cluster it is reached over plain HTTP on port 8000. See [Deployment](deployment.md).

## Secrets

The only secrets are the SCAYLE credentials (`SCAYLE_USERNAME`, `SCAYLE_PASSWORD`). In
Kubernetes they come from the Vault path `athenarc/dg-intent-disambiguation`, through the
Vault operator, as the Secret `dg-intent-disambiguation-app-secrets`. They are never logged
and never included in error messages. For local runs they live in an untracked `.env` file.

## Input Handling

- The input is limited to 2000 characters, the history to 10 messages and the selected
  datasets to 200 ids; larger requests are rejected with `422`.
- The prompt places the input inside `<input>` tags and instructs the model to treat it
  only as text to classify. The model can only answer through the fixed JSON schema, so
  an injected instruction can at worst change the returned label. Prompt-injection inputs
  are part of the benchmark and are classified `out_of_scope`.
- The service does not store inputs. They appear in logs only at `DEBUG` level; at the
  default `INFO` level only the input length is logged.
- Invalid correlation ids (anything other than 1 to 128 letters, digits, `.`, `_`, `:` or
  `-`) are replaced, so the header cannot inject content into the logs.

## Container

The image is based on `python:3.11-slim-bookworm`, contains only the locked runtime
dependencies, and runs as an unprivileged user (uid 10001). The Kubernetes deployment
also sets a read-only root filesystem, drops all capabilities and disallows privilege
escalation. The image can be scanned with the on-demand vulnerability scan workflow (see
[Maintenance](maintenance.md#security-scans)).
