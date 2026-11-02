# Intent benchmark

A larger, independently labelled test set for the intent classifier, alongside the small
regression set in [../queries.yaml](../queries.yaml).

```bash
make benchmark                       # run the classifier on benchmark.jsonl (VPN, .env)
uv run --env-file .env python eval/run_eval.py --queries eval/benchmark/benchmark.jsonl \
    --reuse eval/results/eval-<stamp>.json   # re-score stored predictions after relabelling
```

## How it was built

[build_benchmark.py](build_benchmark.py) builds it in three stages.

1. **Generate.** 198 recipes cross the intent with a phrasing style, a domain, a
   language and a kind of noise. Inputs are written by DeepSeek-V4-Flash and
   GLM-5.3-Flash on SCAYLE in turn, with thinking on and temperature 1. Neither is the
   Qwen model under test. The recipes are grounded in the datasets the platform hosts:
   Greek weather stations, ERA5-Land, cement CO2 emissions, BioTIME, the historical
   encyclopedias (Britannica, Diderot, EncycNet), MathE, the IPB course offerings,
   CEDEFOP, ESCO, ISCO and last-mile delivery. They also cover topics the platform does
   not host.
2. **Judge.** Both models label every input from an annotation guide written separately
   from the production prompt (`JUDGE_PROMPT` in the script), in shuffled batches of 10.
3. **Finalize.** An input is accepted when both judges agree with the intent it was
   generated for. Every other input was reviewed by hand. The decision (keep, relabel,
   mark as contested, or drop) is recorded with a reason in [overrides.yaml](overrides.yaml).

Raw generations and judge labels are kept in `raw/`, so every label can be traced.

## Composition

876 inputs: 679 with a single expected intent (question 289, dataset_search 205,
ambiguous 97, out_of_scope 88), and 197 contested.

| Group | Inputs |
|---|---|
| English phrasing styles across 7 domains (explicit, need statements, access, similar, availability, lookup, aggregation, comparison, trend, ranking, charts, implicit values, yes/no, multi-step, text and education analytics, keywords, research themes, 8 kinds of out-of-scope) | 512 |
| Other languages: Greek, Greeklish, Greek-English mix, French, German, Spanish, Italian, Portuguese, Polish (20 each) | 180 |
| Noise: typos, long and rambling, terse, all caps and emojis | 96 |
| Follow-ups with earlier messages and selected datasets | 40 |
| Contested by design: dataset metadata, general knowledge, learning material, mixed requests, forecasts, research method | 48 |

The generators and judges agreed on 713 inputs. The other 163 were reviewed by hand: 149
became contested and 14 were relabelled. The two judges agree with each other on 87% of
the non-contested inputs. That sets a ceiling: the line between `ambiguous` and the other
intents is fuzzy for keyword inputs, so watch **misroutes** more than accuracy.

## Results (30 Oct 2026, qwen3.8-flash-next)

| Configuration | Strict accuracy | Misroutes | Contested | Degraded | Latency p50 / p95 |
|---|---|---|---|---|---|
| **Prompt v1, thinking off (deployed)** | **96.5%** | **4** | 98.5% | 0 | 1.4 s / 1.7 s |
| Prompt v1, thinking on | 96.9% | 0 | 96.4% | 31 | 2.4 s / 6.9 s |
| Prompt v2 candidate, thinking off | 95.1% | 3 | 97.5% | 0 | 1.5 s / 1.7 s |

With v1 and thinking off:

- Per intent, precision / recall: dataset_search 98.5 / 94.6, question 98.3 / 97.6,
  ambiguous 86.8 / 94.8, out_of_scope 97.8 / 98.9.
- Every English phrasing style, the 7 domains, the 8 kinds of out-of-scope input
  (including prompt injection) and French, German, Spanish, Greek and Greek-English are
  at 95 to 100%. Portuguese and Polish are lowest at 85%, on 20 inputs each.
- Two of the 4 misroutes are dataset licence or API questions that the judges labelled
  dataset_search and the model answered as a question or out of scope. The other two are
  Polish inputs on the boundary between a dataset search and a question.
- Patterns among the 27 errors:
  - **Learning material** marked out of scope ("I need video tutorials on linear algebra",
    "MATHE INTEGRATION BY PARTS EXERCISES").
  - **One-word follow-ups** after a question ("precipitation") read as ambiguous instead
    of the same question.
  - **Terse value phrases** ("average July temperature Heraklion 2019") read as ambiguous.
  - **Keywords that name a dataset** ("ERA5-Land soil moisture France 2005") read as
    ambiguous.

  All except the out-of-scope learning material cost the user one extra click, not a wrong
  page.

Thinking on removes the misroutes, but 31 replies ran out of the 1024-token budget while
still reasoning and fell back to `degraded`. Tail latency also grows fourfold.

The v2 candidate added rules for those error patterns. It traded errors rather than
removing them: dataset-licence rules pulled platform-help questions into dataset_search,
and the learning-material and value-keyword rules pulled topic keywords away from
ambiguous. It was not kept.

The learning-material case is a product decision before it is a prompt change. Should
"linear algebra videos" go to dataset search or to the MathE recommendation endpoint?
Once that is decided, add one targeted rule and re-measure here.

## Fields

| Field | |
|---|---|
| `id` | Hash of the normalised input and history |
| `query`, `context` | What is sent to the service. Follow-ups carry `history` and `dataset_ids`. |
| `intent` | The expected label |
| `acceptable` | Only on contested inputs: every label that counts as correct |
| `slice` | The recipe's phrasing style, noise kind or contested type |
| `domain`, `language` | Where applicable |
| `generator`, `judges` | Which model wrote the input, and what each judge said |
| `review_note` | Why a reviewed input was kept, relabelled or marked as contested |

Contested inputs are those where reasonable people would pick different flows, such as
questions about a dataset's licence, general-knowledge questions, or requests for
learning material. They are scored leniently and kept out of the strict accuracy and the
misroute count.
