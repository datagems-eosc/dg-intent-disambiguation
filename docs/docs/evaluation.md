# Evaluation

The classifier is measured on two labelled sets in the repository's `eval/` folder. Both
run against the real model, so they need access to SCAYLE.

| Set | Inputs | Purpose | Command |
|---|---|---|---|
| Regression set (`eval/queries.yaml`) | 134 | Written alongside the prompt; checks that known cases keep working | `make eval` |
| Benchmark (`eval/benchmark/benchmark.jsonl`) | 876 | Independent measurement: written and labelled by other model families, reviewed by hand | `make benchmark` |

## Metrics

- **Accuracy**: share of inputs with exactly the expected intent, over the inputs that have
  a single expected intent.
- **Misroutes**: errors that send the user to the wrong place: a dataset search answered
  as a question or the other way round, or a data request marked `out_of_scope`. Answering
  `ambiguous` for a clear input is not a misroute: it costs the user one click.
- **Contested inputs**: inputs on which reasonable people would pick different flows
  (questions about a dataset's licence, general-knowledge questions, requests for learning
  material, bare keywords the annotators disagreed on). Each has a list of acceptable
  intents and is reported separately.
- **Degraded**: answers produced by the fallback because the model failed.
- **Latency**: median and 95th percentile per request.

The report also breaks accuracy down by phrasing style, language and domain, and lists
every error.

## Benchmark

The benchmark was built in three stages by `eval/benchmark/build_benchmark.py`:

1. **Generate.** 198 recipes cross the intent with a phrasing style, a domain, a language
   and a kind of noise. DeepSeek-V4-Flash and GLM-5.3-Flash on SCAYLE write the inputs in
   turn. Neither is the Qwen model under test. The recipes are grounded in the datasets
   the platform hosts (Greek weather stations, ERA5-Land, cement CO2 emissions, BioTIME,
   the Britannica, Diderot and EncycNet encyclopedias, MathE, CEDEFOP, ESCO, ISCO,
   last-mile delivery) and in topics it does not host.
2. **Judge.** Both models label every input from an annotation guide written separately
   from the production prompt.
3. **Review.** An input is accepted when both judges agree with the intent it was
   generated for. The remaining 163 inputs were reviewed by hand; every decision and its
   reason is recorded in `eval/benchmark/overrides.yaml`.

### Composition

| Group | Inputs |
|---|---|
| English phrasing styles across 7 domains, including 8 kinds of out-of-scope input and prompt injection | 512 |
| Greek, Greeklish, Greek-English mix, French, German, Spanish, Italian, Portuguese, Polish (20 each) | 180 |
| Noise: typos, long and rambling, terse, all caps and emojis | 96 |
| Follow-ups with earlier messages and selected datasets | 40 |
| Contested by design | 48 |

679 inputs have a single expected intent (question 289, dataset_search 205, ambiguous 97,
out_of_scope 88) and 197 are contested. The two judges agree with each other on 87% of the
non-contested inputs: the line between `ambiguous` and the other intents is fuzzy for
keyword inputs, which is why misroutes matter more than accuracy.

### Results

Measured on 30 October 2026 with `qwen3.8-flash-next`:

| Configuration | Accuracy | Misroutes | Contested | Degraded | Latency p50 / p95 |
|---|---|---|---|---|---|
| **Prompt v1, thinking off (deployed)** | **96.5%** | **4** | 98.5% | 0 | 1.4 s / 1.7 s |
| Prompt v1, thinking on | 96.9% | 0 | 96.4% | 31 | 2.4 s / 6.9 s |
| Prompt v2 candidate, thinking off | 95.1% | 3 | 97.5% | 0 | 1.5 s / 1.7 s |

With the deployed configuration:

- Precision / recall per intent: dataset_search 98.5 / 94.6, question 98.3 / 97.6,
  ambiguous 86.8 / 94.8, out_of_scope 97.8 / 98.9.
- Every English phrasing style, all 7 domains, all kinds of out-of-scope input
  (including prompt injection) and French, German, Spanish, Greek and Greek-English score
  95 to 100%. Portuguese and Polish are lowest at 85%, on 20 inputs each.
- The regression set scores 100% with no misroutes.

With thinking on, 31 replies ran out of the token budget while still reasoning and fell
back to the degraded answer. The v2 candidate added rules for the error patterns below; it
moved errors between intents rather than removing them, so it was not kept.

### Known Weak Spots

- **Learning material** ("I need video tutorials on linear algebra", "MATHE INTEGRATION
  BY PARTS EXERCISES") is sometimes marked `out_of_scope`. Whether such requests should
  go to dataset search or to the MathE recommendation endpoint is still to be decided.
- **Questions about a dataset itself** (licence, API, citation) do not fit the four
  intents cleanly; two of the four misroutes are of this kind.
- **One-word follow-ups** after a question ("precipitation"), **terse value phrases**
  ("average July temperature Heraklion 2019") and **keywords naming a dataset**
  ("ERA5-Land soil moisture France 2005") are often answered `ambiguous`. These cost the
  user one extra click.

## Running the Evaluation

```bash
make eval        # regression set
make benchmark   # benchmark, about 5 minutes

# compare settings without changing the deployment
uv run --env-file .env python eval/run_eval.py \
    --queries eval/benchmark/benchmark.jsonl --prompt-version v2 --thinking

# evaluate a deployed instance
uv run python eval/run_eval.py --url https://{host}/dg-intent-disambiguation/api/v1/intent \
    --token "$TOKEN"

# re-score stored predictions after relabelling, without calling the model
uv run python eval/run_eval.py --queries eval/benchmark/benchmark.jsonl \
    --reuse eval/results/eval-<stamp>.json
```

Every run writes the full set of answers to `eval/results/`.
