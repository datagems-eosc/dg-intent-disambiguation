"""Measure the intent classifier against labelled inputs.

Reads eval/queries.yaml (the small regression set) or a JSONL benchmark such as
eval/benchmark/benchmark.jsonl. Runs the classifier in-process with the settings
from the environment (`make eval` loads .env), or calls a deployed service with
--url. Prints accuracy, per-intent precision and recall, a confusion table,
misroutes, latency and, for the benchmark, accuracy per slice, language and
domain. Writes the full result to eval/results/.

A misroute is an error that sends the user to the wrong page: a dataset search
answered as a question (or the other way round), or a data request marked
out_of_scope. Answering "ambiguous" for a clear input only costs the user one click.

Items with an `acceptable` list are contested: people would disagree on one right
answer. They count as correct when the prediction is any acceptable label, and are
kept out of the strict accuracy, confusion table and misroute count.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from intent_disambiguation.classifier import IntentClassifier, PromptTemplate
from intent_disambiguation.config import Settings
from intent_disambiguation.llm import ScayleClient
from intent_disambiguation.logging_setup import setup_logging
from intent_disambiguation.schemas import Intent, IntentContext

EVAL_DIR = Path(__file__).parent
INTENTS = [intent.value for intent in Intent]
DATA_INTENTS = {Intent.DATASET_SEARCH.value, Intent.QUESTION.value}
BREAKDOWNS = ("slice", "language", "domain")


def load_items(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        items = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
        return [{**item, "expected": item["intent"]} for item in items]
    data = yaml.safe_load(path.read_text("utf-8"))
    return [{"expected": intent, **item} for intent in INTENTS for item in data.get(intent, [])]


def input_key(item: dict) -> str:
    return json.dumps([item["query"], item.get("context")], sort_keys=True, ensure_ascii=False)


def is_contested(item: dict) -> bool:
    return bool(item.get("acceptable"))


def is_correct(item: dict, predicted: str) -> bool:
    if is_contested(item):
        return predicted in item["acceptable"]
    return predicted == item["expected"]


def is_misroute(expected: str, predicted: str) -> bool:
    if expected in DATA_INTENTS and predicted in DATA_INTENTS:
        return expected != predicted
    return expected in DATA_INTENTS and predicted == Intent.OUT_OF_SCOPE.value


async def run_local(items: list[dict], settings: Settings, concurrency: int) -> list[dict]:
    llm = ScayleClient(
        settings.scayle_base_url,
        settings.scayle_username,
        settings.scayle_password,
        verify_ssl=settings.scayle_verify_ssl,
        timeout=settings.scayle_timeout,
    )
    classifier = IntentClassifier(
        llm,
        settings.intent_model,
        PromptTemplate.load(settings.prompt_version),
        min_confidence=settings.intent_min_confidence,
        enable_thinking=settings.intent_enable_thinking,
        max_tokens=settings.intent_max_tokens,
    )

    async def classify(item: dict) -> dict:
        context = IntentContext(**item["context"]) if item.get("context") else None
        response = await classifier.classify(item["query"], context)
        return response.model_dump(mode="json")

    try:
        return await _run_all(items, classify, concurrency)
    finally:
        await llm.aclose()


async def run_remote(items: list[dict], url: str, token: str | None, concurrency: int):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:

        async def classify(item: dict) -> dict:
            body = {"query": item["query"], "context": item.get("context")}
            response = await client.post(url, json=body)
            response.raise_for_status()
            return response.json()

        return await _run_all(items, classify, concurrency)


async def _run_all(items: list[dict], classify, concurrency: int) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(item: dict) -> dict:
        async with semaphore:
            started = time.perf_counter()
            response = await classify(item)
            latency_ms = round((time.perf_counter() - started) * 1000)
        return {**item, "response": response, "latency_ms": latency_ms}

    return await asyncio.gather(*(one(item) for item in items))


def summarize(results: list[dict]) -> dict:
    strict = [r for r in results if not is_contested(r)]
    contested = [r for r in results if is_contested(r)]

    confusion = {e: {p: 0 for p in INTENTS} for e in INTENTS}
    for r in strict:
        confusion[r["expected"]][r["response"]["intent"]] += 1

    per_intent = {}
    for intent in INTENTS:
        tp = confusion[intent][intent]
        predicted = sum(confusion[e][intent] for e in INTENTS)
        actual = sum(confusion[intent].values())
        per_intent[intent] = {
            "precision": tp / predicted if predicted else None,
            "recall": tp / actual if actual else None,
            "support": actual,
        }

    breakdowns = {}
    for key in BREAKDOWNS:
        groups: dict[str, list[bool]] = defaultdict(list)
        for r in results:
            if r.get(key) is not None:
                groups[str(r[key])].append(is_correct(r, r["response"]["intent"]))
        if len(groups) > 1:
            breakdowns[key] = {
                group: {"accuracy": sum(hits) / len(hits), "n": len(hits)}
                for group, hits in groups.items()
            }

    contested_predictions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in contested:
        contested_predictions[r.get("slice", "contested")][r["response"]["intent"]] += 1

    latencies = sorted(r["latency_ms"] for r in results)
    return {
        "total": len(results),
        "strict_total": len(strict),
        "accuracy": (
            sum(is_correct(r, r["response"]["intent"]) for r in strict) / len(strict)
            if strict
            else None
        ),
        "contested_total": len(contested),
        "contested_accuracy": (
            sum(is_correct(r, r["response"]["intent"]) for r in contested) / len(contested)
            if contested
            else None
        ),
        "misroutes": sum(is_misroute(r["expected"], r["response"]["intent"]) for r in strict),
        "degraded": sum(r["response"]["degraded"] for r in results),
        "per_intent": per_intent,
        "confusion": confusion,
        "breakdowns": breakdowns,
        "contested_predictions": {k: dict(v) for k, v in contested_predictions.items()},
        "latency_ms": {
            "p50": statistics.median(latencies),
            "p95": latencies[max(0, round(0.95 * len(latencies)) - 1)],
            "max": latencies[-1],
        },
    }


def pct(value):
    return "  -  " if value is None else f"{value:5.1%}"


def print_report(summary: dict, results: list[dict], label: str, max_errors: int) -> None:
    print(f"\n== {label}")
    print(
        f"accuracy {pct(summary['accuracy'])} ({summary['strict_total']} inputs) | "
        f"misroutes {summary['misroutes']} | degraded {summary['degraded']} | "
        f"latency p50 {summary['latency_ms']['p50']:.0f} ms, "
        f"p95 {summary['latency_ms']['p95']} ms"
    )
    if summary["contested_total"]:
        print(
            f"contested: {pct(summary['contested_accuracy'])} within the acceptable labels "
            f"({summary['contested_total']} inputs)"
        )

    print(f"\n{'':16}{'precision':>10}{'recall':>9}{'n':>6}")
    for intent, scores in summary["per_intent"].items():
        print(
            f"{intent:16}{pct(scores['precision']):>10}{pct(scores['recall']):>9}"
            f"{scores['support']:>6}"
        )

    short = {
        "dataset_search": "dataset",
        "question": "question",
        "ambiguous": "ambig",
        "out_of_scope": "oos",
    }
    print("\nexpected \\ predicted" + "".join(f"{short[p]:>10}" for p in INTENTS))
    for expected, row in summary["confusion"].items():
        print(f"{expected:20}" + "".join(f"{row[p]:>10}" for p in INTENTS))

    for key, groups in summary["breakdowns"].items():
        print(f"\nby {key} (worst first)")
        ordered = sorted(groups.items(), key=lambda kv: (kv[1]["accuracy"], -kv[1]["n"]))
        for group, scores in ordered:
            print(f"  {group:30}{pct(scores['accuracy']):>8}{scores['n']:>6}")

    if summary["contested_predictions"]:
        print("\ncontested slices: predictions")
        for slice_name, counts in sorted(summary["contested_predictions"].items()):
            spread = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
            print(f"  {slice_name:30}{spread}")

    errors = [r for r in results if not is_correct(r, r["response"]["intent"])]
    errors.sort(key=lambda r: not is_misroute(r["expected"], r["response"]["intent"]))
    if errors:
        shown = errors if max_errors < 0 else errors[:max_errors]
        print(f"\nErrors (! = misroute), {len(shown)} of {len(errors)}:")
        for r in shown:
            mark = (
                "!"
                if not is_contested(r) and is_misroute(r["expected"], r["response"]["intent"])
                else " "
            )
            expected = "/".join(r["acceptable"]) if is_contested(r) else r["expected"]
            query = r["query"].replace("\n", " ")
            follow_up = " [follow-up]" if r.get("context") else ""
            print(
                f" {mark} {expected:>14} -> {r['response']['intent']:<14} "
                f"({r['response']['confidence']:.2f}) {query[:110]}{follow_up}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queries", type=Path, default=EVAL_DIR / "queries.yaml")
    parser.add_argument("--model", help="override INTENT_MODEL")
    parser.add_argument("--prompt-version", help="override PROMPT_VERSION")
    parser.add_argument(
        "--thinking", action=argparse.BooleanOptionalAction, help="override INTENT_ENABLE_THINKING"
    )
    parser.add_argument("--min-confidence", type=float, help="override INTENT_MIN_CONFIDENCE")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-errors", type=int, default=60, help="-1 prints every error")
    parser.add_argument("--url", help="evaluate a deployed service, e.g. .../api/v1/intent")
    parser.add_argument("--token", help="bearer token for --url")
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "results")
    parser.add_argument(
        "--reuse",
        type=Path,
        help="score the predictions stored in an earlier results file instead of calling the "
        "model, e.g. after relabelling",
    )
    args = parser.parse_args()
    # Fallbacks are still logged; per-request lines would bury the report
    setup_logging(json_logs=False, log_level="WARNING")

    items = load_items(args.queries)
    if args.reuse:
        previous = json.loads(args.reuse.read_text("utf-8"))
        stored = {input_key(r): r for r in previous["results"]}
        missing = [item for item in items if input_key(item) not in stored]
        if missing:
            sys.exit(f"{len(missing)} inputs have no stored prediction in {args.reuse}")
        label = f"{previous['label']} | rescored on {args.queries.name}"
        results = [
            {
                **item,
                "response": stored[input_key(item)]["response"],
                "latency_ms": stored[input_key(item)]["latency_ms"],
            }
            for item in items
        ]
    elif args.url:
        label = f"remote {args.url}"
        results = asyncio.run(run_remote(items, args.url, args.token, args.concurrency))
    else:
        settings = Settings.from_env()
        overrides = {
            "intent_model": args.model,
            "prompt_version": args.prompt_version,
            "intent_enable_thinking": args.thinking,
            "intent_min_confidence": args.min_confidence,
        }
        settings = replace(settings, **{k: v for k, v in overrides.items() if v is not None})
        if not settings.scayle_username:
            sys.exit("SCAYLE_USERNAME is not set; copy .env.example to .env and fill it in")
        label = (
            f"{args.queries.name} | model {settings.intent_model} | "
            f"prompt {settings.prompt_version} | thinking {settings.intent_enable_thinking} | "
            f"min confidence {settings.intent_min_confidence}"
        )
        results = asyncio.run(run_local(items, settings, args.concurrency))

    summary = summarize(results)
    print_report(summary, results, label, args.max_errors)

    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.output / f"eval-{stamp}.json"
    out.write_text(
        json.dumps(
            {"label": label, "summary": summary, "results": results}, indent=2, ensure_ascii=False
        ),
        "utf-8",
    )
    print(f"\nFull results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
