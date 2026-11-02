# FAQ

This document answers frequently asked questions about the Intent Disambiguation service.

## General Questions

### What is the Intent Disambiguation service?

A service that reads what a user typed into the DataGEMS search box and decides whether
they want to find datasets, get an answer computed from data, either of the two, or
something that is not a data request. The Gateway API uses the answer to pick the
discovery flow and the view to open.

### Does it search for datasets or answer questions itself?

No. It only classifies the input and returns a keyword query. The Gateway runs
cross-dataset discovery and in-dataset discovery.

### How is it different from the Gateway's query disambiguation?

The Gateway's `/api/search/disambiguate-query` endpoint rewrites unclear terms inside a
query for a chosen set of datasets. Intent disambiguation runs earlier and decides which
flow should handle the query at all.

### Which languages are supported?

Any language the model understands. The benchmark covers English, Greek, Greeklish, mixed
Greek and English, French, German, Spanish, Italian, Portuguese and Polish. The
`search_query` is always in English.

## Technical Questions

### Which model does it use?

`qwen3.8-flash-next` on SCAYLE by default, with its reasoning phase switched off. The model
is set with `INTENT_MODEL`.

### How fast is it?

About 0.7 s per request, and 1.1 s at the 95th percentile, measured one request at a time on benchmark inputs.

### What happens when SCAYLE is down?

The endpoint still answers `200` with `intent: ambiguous` and `degraded: true`, so the UI
asks the user to choose. See [Degraded Answers](error-codes.md#degraded-answers).

### Why do I get `ambiguous` for a clear request?

Either the model's confidence was below `INTENT_MIN_CONFIDENCE`, or the answer is degraded
(check the `degraded` field), or the input is a bare topic or keyword phrase, which the
service deliberately leaves to the user. Short keyword inputs that name a dataset or ask
for a value are a known weak spot; see [Evaluation](evaluation.md#known-weak-spots).

### Why does the response not explain its decision?

An explanation costs generation time. Prompt `v1` returned a one-sentence `reason`;
dropping it made answers about 100 ms faster at the median and 430 ms at the 95th
percentile, with the same accuracy. The `confidence` field and the logs are the
diagnostics now.

### Can I send the conversation so far?

Yes, as `context.history` and `context.dataset_ids`. Short follow-ups such as "and per
month?" are then classified using the earlier messages, and `search_query` is completed
from them.

### Is the input stored?

No. The service is stateless, and inputs are logged only at `DEBUG` level. See
[Logging](logging.md#privacy).

## Known Issues

- Requests for mathematics learning material are sometimes classified `out_of_scope`.
- Questions about a dataset's licence, API or citation do not fit the four intents
  cleanly.
- The `question` flow needs in-dataset discovery to accept the selected dataset ids,
  which the Gateway does not forward yet.
