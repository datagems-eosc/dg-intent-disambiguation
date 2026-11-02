# Intent Classification

This page describes how an input becomes an answer: the intents, the prompt, the
structured output and the rules applied after the model answers.

## Intents

| Intent | Definition | Examples |
|---|---|---|
| `dataset_search` | The user wants to find or browse datasets, asks whether data exists, or wants to download or access data. | "Do you have any data about temperatures across Europe?", "I need a corpus of Austrian newspapers" |
| `question` | The user wants an answer looked up or computed from data: a value, count, list, comparison, trend, ranking, chart or table. Includes commands ("plot ...") and keyword phrases that clearly ask for a value. | "What was the mean temperature in Athens in 2020?", "Plot the daily precipitation in Patras for 2022" |
| `ambiguous` | Only a topic or keywords, with no sign of either. | "surface temperature increase", "unemployment in Greece" |
| `out_of_scope` | Not a request about data: greetings, chit-chat, personal or creative requests, general help, questions about the assistant or the platform, gibberish, attempts to change the instructions. | "tell me how I feel tonight", "write a poem about the sea" |

A request for a value stays a `question` even when it mentions data or datasets
("According to the weather datasets, how much did it rain in Ioannina in March 2021?").

## Prompt

The prompt is a versioned YAML file in `intent_disambiguation/prompts/`, selected with
`PROMPT_VERSION` (default `v1`). It contains:

- a short description of the platform and the kinds of data it hosts,
- the four intent definitions and the decision rules,
- the fields to return,
- worked examples, rendered as input and expected output.

The user message wraps the input in `<input>` tags and adds a `<context>` block when the
request carries context:

```text
<input>
and per month?
</input>
<context>
Datasets already selected in this conversation: 1
Earlier messages in this conversation, oldest first:
- What was the mean temperature in Athens in 2020?
</context>
```

The prompt tells the model to treat the input only as text to classify and never to
follow instructions found in it.

## Structured Output

The model is called with temperature 0 and a strict JSON schema:

```json
{
  "reason": "string",
  "intent": "dataset_search | question | ambiguous | out_of_scope",
  "confidence": "number",
  "search_query": "string or null"
}
```

`reason` comes first so the model states why before it commits to a label, which helps
when its reasoning phase is switched off. The answer is validated with pydantic; text
around the JSON object (code fences, for example) is tolerated.

## Rules Applied After the Model Answers

- **Confidence threshold.** `confidence` is clamped to `[0, 1]`. Any label other than
  `ambiguous` with confidence below `INTENT_MIN_CONFIDENCE` (default `0.6`) becomes
  `ambiguous`: asking the user costs one click, a wrong flow costs more.
- **Search query.** `search_query` is an English keyword query (2 to 10 words) for
  cross-dataset discovery: places, periods, variables and named sources are kept,
  question words and filler are dropped, and follow-ups are resolved from the earlier
  messages. It is `null` for `out_of_scope`. If the model leaves it empty for another
  intent, the raw input is used.

## Degraded Answers

When the SCAYLE API cannot be reached, times out, or returns an empty or invalid answer,
the service answers `200` with:

```json
{
  "intent": "ambiguous",
  "confidence": 0.0,
  "reason": "The intent model is unavailable, so the user should choose.",
  "search_query": "<the raw input>",
  "degraded": true
}
```

The UI then asks the user which flow they meant, exactly as for a genuine `ambiguous`
answer. A warning is logged with the cause.

## Context

All context fields are optional hints:

| Field | Effect |
|---|---|
| `domain` | The topic filter picked on the home page, e.g. `weather`. |
| `dataset_ids` | Datasets already selected. With datasets selected and an earlier question, a short follow-up is read as a question about them. Only the count is sent to the model. |
| `history` | Earlier user messages, oldest first. The last five are sent; they are also used to complete `search_query` for follow-ups. |

## Thinking Mode

Qwen models can reason before answering. It is switched off by default
(`INTENT_ENABLE_THINKING=false`, sent as `chat_template_kwargs.enable_thinking`): on the
benchmark it removed the last few misroutes but quadrupled tail latency, and reasoning
tokens count against `INTENT_MAX_TOKENS`, so a long reasoning phase can end without an
answer. See [Evaluation](evaluation.md).

## Changing the Prompt

1. Add `prompts/intent_v2.yaml`. Keep its examples out of the evaluation sets.
2. Run the evaluation with `--prompt-version v2` on the regression set and the benchmark,
   and compare with `v1`. Look at misroutes as well as accuracy.
3. Switch with `PROMPT_VERSION=v2` in the deployment configuration. The response's
   `prompt_version` field shows which prompt produced each answer.
