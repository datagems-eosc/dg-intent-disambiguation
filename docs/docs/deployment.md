# Deployment

The service is part of the DataGEMS platform offered through an existing deployment, following the DataGEMS release and deployment procedures over a managed infrastructure. The purpose of this section is not to detail the deployment processes put in place by the DataGEMS team.

## Docker

The service is offered as a Docker image through the DataGEMS GitHub Organization Packages, as `ghcr.io/datagems-eosc/dg-intent-disambiguation`.

The image is built from the repository's `Dockerfile`:

- based on `python:3.11-slim-bookworm`,
- runtime dependencies installed with `uv` from the locked `uv.lock`, without development tools,
- runs `uvicorn intent_disambiguation.main:app` on port 8000 as an unprivileged user (uid 10001),
- works with a read-only root filesystem.

Build and publication are handled by the `.github/workflows/docker-publish.yml` GitHub Actions workflow, which is triggered when a `v*` tag is pushed (i.e. on new releases). The image tag matches the git tag.

To run the image locally:

```bash
make docker-run   # builds the image and runs it with the settings in .env
```

## Kubernetes

The Kubernetes manifests are kept in a separate deployment repository, one folder per environment, applied with kustomize. In the development environment the service runs in the `athenarc` namespace as:

| Resource | Name |
|---|---|
| Deployment | `dg-intent-disambiguation-api` (1 replica, 128 Mi / 100 m requested, 512 Mi / 500 m limit) |
| Service | `dg-intent-disambiguation-api-service`, port 8000 |
| Ingress and HTTPRoute | path prefix `/dg-intent-disambiguation`, rewritten to `/` |
| ConfigMap | `dg-intent-disambiguation-api-config`, the settings described in [Configuration](configuration.md) |
| VaultStaticSecret | creates `dg-intent-disambiguation-app-secrets` from the Vault path `athenarc/dg-intent-disambiguation` |

The pod resolves the AAI host name (`datagems-dev.scayle.es`) to the ingress controller through `hostAliases`, so that it can fetch the token signing keys from inside the cluster.

### Probes

Neither probe depends on SCAYLE. When the LLM is down the intent endpoint still answers (degraded), so the pod must stay in the Service:

| Probe | Endpoint |
|---|---|
| Liveness | `GET /` |
| Readiness | `GET /monitoring/ready` |

`GET /monitoring/health-check` reports SCAYLE status for diagnostics only. See [Maintenance](maintenance.md).

## Configuration

In order for the service to operate properly, the needed configuration values must be set to match the environment that it must operate in. The needed configuration is described in the relevant [Configuration](configuration.md) section.
