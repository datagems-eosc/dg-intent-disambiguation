# Maintenance

This document provides guidance on checking the health of the Intent Disambiguation
service and on the routine tasks that keep it working.

## Health Checks

### Liveness and Readiness Probes

Both probes are pure HTTP and do **not** depend on SCAYLE, so an LLM outage never takes
the pod out of the Service; the intent endpoint answers with degraded results instead.

```bash
curl -X GET "https://{host}/dg-intent-disambiguation/"
curl -X GET "https://{host}/dg-intent-disambiguation/monitoring/ready"
```

Expected responses:

```json
{"service": "dg-intent-disambiguation", "version": "0.2.0"}
{"status": "ready"}
```

### Dependency Health Check

Reports whether SCAYLE is reachable and the configured model is listed. It is purely
diagnostic: it **always** returns HTTP 200 from a live pod and reports problems in the
body.

```bash
curl -X GET "https://{host}/dg-intent-disambiguation/monitoring/health-check"
```

Expected response:

```json
{
  "status": "healthy",
  "version": "0.2.0",
  "scayle": {"status": "healthy", "model": "qwen3.8-flash-next", "model_available": true}
}
```

When SCAYLE is unreachable, or the model is no longer listed, `status` becomes `degraded`
and `scayle.message` explains why.

## Routine Tasks

### The Model Was Renamed or Removed

SCAYLE model ids are case sensitive and are renamed from time to time. When
`/monitoring/health-check` reports `model_available: false`, every answer is degraded.
List the available models, pick the replacement, set `INTENT_MODEL` in the ConfigMap and
restart the deployment. Run the evaluation with `--model <id>` before switching to a
different model family.

### Degraded Answers

Count the `Intent model unavailable, falling back to ambiguous` warnings in the logs. Their
`error` field shows the cause: connection errors (SCAYLE or the VPN route down),
`HTTP 401` after renewal (credentials changed in Vault), or `finish_reason=length` (the
token budget is too small, usually because thinking was switched on).

### Changing the Prompt

Add a new prompt version, compare it with the current one on the regression set and the
benchmark, and switch with `PROMPT_VERSION`. See
[Intent Classification](intent-classification.md#changing-the-prompt) and
[Evaluation](evaluation.md).

### Tightening Authentication

Once the Gateway's client id has been confirmed in the logs (`ClientId`), set
`ALLOWED_CLIENTS` to it. See [Configuration](configuration.md#authentication).

## Releases

1. Bump `version` in `pyproject.toml` and `intent_disambiguation/__init__.py`.
2. Push a tag `vX.Y.Z`. The Docker publish workflow builds and pushes
   `ghcr.io/datagems-eosc/dg-intent-disambiguation:vX.Y.Z`.
3. Update the image tag in the deployment repository and apply it.
4. Publish the documentation for the new version with the Deploy Docs workflow.

## Security Scans

The repository offers on-demand GitHub Actions workflows, started from the Actions tab:

| Workflow | What it does |
|---|---|
| CodeQL Scan (On-Demand) | Static analysis of the Python code and the workflow files |
| Vulnerability Scan (On-Demand) | Trivy scan of the Dockerfile configuration and of a published image tag (critical and high findings) |
| Code Metrics (On-Demand) | Maintainability index, cyclomatic complexity and lines of code with radon |

Each uploads its report as a workflow artifact (CodeQL results go to the repository's
Security tab).
