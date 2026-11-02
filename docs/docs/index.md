# Intent Disambiguation

[![Commit activity](https://img.shields.io/github/commit-activity/m/datagems-eosc/dg-intent-disambiguation)](https://github.com/datagems-eosc/dg-intent-disambiguation/commits)
[![License](https://img.shields.io/github/license/datagems-eosc/dg-intent-disambiguation)](https://github.com/datagems-eosc/dg-intent-disambiguation/blob/main/LICENSE)

This is the documentation site for the Intent Disambiguation service. The service is part of the wider [DataGEMS](https://datagems.eu/) platform.

DataGEMS lets users look for relevant datasets (cross-dataset discovery) or for facts
computed from data (in-dataset discovery). The platform's home page has a single search
box, so something has to decide which of the two a user meant. This service makes that
decision: it reads the text the user typed and returns one of four intents, together with
a keyword query for the discovery step.

| Intent | The user wants | The platform should |
|---|---|---|
| `dataset_search` | to find or browse datasets | run cross-dataset discovery |
| `question` | an answer computed from data | find datasets with cross-dataset discovery, then run in-dataset discovery on them |
| `ambiguous` | either, it is not clear which | ask the user which one they meant |
| `out_of_scope` | something that is not a data request | show a short message and example queries |

## Key Features

- **One call, one answer**: a single LLM call with strict JSON-schema output returns the
  intent, a confidence, a one-sentence reason and an English keyword query.
- **Any language**: inputs in Greek, Greeklish, French, German, Spanish, Italian,
  Portuguese and Polish are handled like English ones.
- **Conversation aware**: optional context (selected datasets, earlier messages, the
  home-page topic filter) lets short follow-ups such as "and per month?" be read correctly.
- **Never blocks the home page**: if the LLM is unavailable the service still answers,
  with `ambiguous` and `degraded: true`, so the UI falls back to asking the user.
- **Measured**: an 876-input benchmark written and labelled by other model families
  tracks accuracy and misroutes per phrasing style, language and domain (see
  [Evaluation](evaluation.md)).
- **Platform-native**: DataGEMS AAI bearer tokens, the Gateway's `x-tracking-correlation`
  header, structured JSON logs and Kubernetes probes.

## How It Works

1. The Gateway API forwards the user's text, and optionally the conversation context, to
   `POST /api/v1/intent`.
2. The service validates the caller's token and renders a versioned prompt with the input.
3. The SCAYLE-hosted LLM (`qwen3.8-flash-next` by default) answers in a fixed JSON schema.
4. Labels below the confidence threshold become `ambiguous`; the keyword query is filled
   in or cleared depending on the intent.
5. The Gateway runs the matching discovery flow and tells the UI which view to open (see
   the [Integration Guide](integration.md)).

The service only classifies. It never calls cross-dataset or in-dataset discovery itself.

!!! note "Not the same as query disambiguation"

    The Gateway's `/api/search/disambiguate-query` endpoint, served through the Task
    Orchestrator, rewrites unclear terms *inside* a query ("Zurich: the city or the
    canton?"). Intent disambiguation decides *which flow* should handle the query.
