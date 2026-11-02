"""Build the intent benchmark: generate inputs with LLMs, label them with LLM judges.

The inputs are written by model families other than the one under test (DeepSeek
and GLM on SCAYLE, never Qwen), from recipes that cross intent with phrasing
style, domain, language and noise. Two judges then label every input from an
annotation guide written separately from the production prompt. An input whose
judges both agree with the intent it was generated for is accepted; every other
input goes to review, and the decisions are recorded in overrides.yaml.

    uv run --env-file .env python eval/benchmark/build_benchmark.py generate
    uv run --env-file .env python eval/benchmark/build_benchmark.py judge
    uv run --env-file .env python eval/benchmark/build_benchmark.py finalize

`generate` and `judge` write raw/*.jsonl and skip work already done there, so an
interrupted run can be resumed. `finalize` writes benchmark.jsonl and review.jsonl.
"""

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
import unicodedata
import uuid
from pathlib import Path

import yaml

from intent_disambiguation.classifier import PROMPTS_DIR
from intent_disambiguation.config import Settings
from intent_disambiguation.llm import ScayleClient, ScayleError
from intent_disambiguation.logging_setup import setup_logging

HERE = Path(__file__).parent
RAW = HERE / "raw"
GENERATED = RAW / "generated.jsonl"
JUDGED = RAW / "judged.jsonl"
OVERRIDES = HERE / "overrides.yaml"
BENCHMARK = HERE / "benchmark.jsonl"
REVIEW = HERE / "review.jsonl"

GENERATORS = ["deepseek-v4-flash-dspark", "glm-5.3-flash"]
JUDGES = ["deepseek-v4-flash-dspark", "glm-5.3-flash"]
JUDGE_BATCH = 10

DOMAINS = {
    "weather_climate": (
        "hourly temperature and humidity from Greek weather stations; ERA5-Land climate "
        "reanalysis from ECMWF (from 1950, 0.1 degree grid): air temperature, precipitation, "
        "soil moisture, wind, snow"
    ),
    "emissions_environment": (
        "Global Carbon Project CO2 emissions from cement production by country and year; "
        "BioTIME biodiversity time series of species abundance at study sites worldwide"
    ),
    "historical_texts": (
        "digitised historical encyclopedias: Encyclopaedia Britannica 7th (1830-1842) and 9th "
        "(1875-1889) editions, Diderot's Encyclopedie (1751-1772), EncycNet (22 German "
        "encyclopedias, 18th to early 20th century); used for linguistic analysis such as term "
        "frequencies, sentiment over time and collocations"
    ),
    "education": (
        "MathE, a higher-education mathematics platform: student answers to assessment "
        "questions by topic (linear algebra, integration, probability, statistics, ...), "
        "question banks with correct and wrong answers, pedagogic PDF material and videos; "
        "university course offerings from the Polytechnic Institute of Braganca"
    ),
    "labour_market": (
        "CEDEFOP skills forecast (employment, labour force and replacement demand by country, "
        "sector, occupation and qualification, up to 2035); the ESCO classification of skills, "
        "competences and occupations; the ISCO occupation taxonomy"
    ),
    "logistics": (
        "last-mile delivery data: geolocated customers and parcel payloads used for vehicle "
        "routing research"
    ),
    "off_catalog": (
        "topics the platform may not host yet, for example public health, housing prices, "
        "elections, energy consumption, tourism, agriculture, sports statistics"
    ),
}

INTENTS = {
    "dataset_search": (
        "The user wants to FIND, browse or download DATASETS, or to learn what data exists. "
        "They are not asking for a specific answer computed from the data."
    ),
    "question": (
        "The user wants a specific ANSWER looked up or computed from data: a value, a count, "
        "records, a comparison, a trend, a ranking, a chart or a table. They are not asking "
        "which datasets exist."
    ),
    "ambiguous": (
        "The input names only a topic or theme (keywords or a short phrase) and gives no sign "
        "of whether the user wants datasets or an answer; both readings are plausible. Do not "
        "use words such as data, dataset, find, search, show, how, what, which, plot or list."
    ),
    "out_of_scope": "The input is NOT a request for data or for an answer derived from data.",
}

SLICES = {
    "dataset_search": {
        "explicit": "asks directly for datasets, data or corpora on a topic",
        "need_statement": "describes a need, e.g. for a thesis, report, model or course",
        "access_format": "about downloading or accessing data, file formats, APIs, licences",
        "similar": "asks for datasets similar to, or combinable with, a named dataset",
        "availability": "asks what data the platform has, or whether data on X exists",
    },
    "question": {
        "lookup": "a single fact or value for a place, time or entity",
        "aggregation": "an average, total, count, maximum or minimum",
        "comparison": "compares two or more places, periods or groups",
        "trend": "a change or trend over time",
        "ranking": "a top-k or ranking",
        "visualization": "a command to plot, chart, map or tabulate values",
        "implicit": "a noun phrase or keywords that clearly ask for a computed value, no "
        "question word (e.g. 'monthly mean temperature Athens 2020')",
        "yes_no": "a yes or no question about the data",
        "multi_step": "needs several steps or a combination of conditions to answer",
    },
    "ambiguous": {
        "keywords": "2 to 4 topic keywords",
        "single_term": "a single word or term",
        "topic_place_time": "a topic with a place and/or period, nothing else",
        "research_theme": "a research theme or title-like phrase",
    },
}

DOMAIN_SPECIFIC_QUESTION_SLICES = {
    "text_analytics": (
        "historical_texts",
        "linguistic analysis: term frequencies, sentiment over time, collocations, mentions",
    ),
    "education_analytics": (
        "education",
        "analysis of student answers, question difficulty, success rates, common mistakes",
    ),
}

OUT_OF_SCOPE_SLICES = {
    "greeting": "greetings, thanks and small talk",
    "personal": "personal, emotional or wellbeing remarks",
    "creative": "creative writing requests: poems, stories, jokes",
    "assistant": "general assistant tasks: emails, CVs, translation, code, summarising text",
    "platform_help": "help with the website or account: login, upload, pricing, what is this",
    "gibberish": "keyboard mashing, random characters, emojis only",
    "injection": "attempts to manipulate the system: reveal instructions, force an answer, "
    "role-play as another assistant",
    "real_world_action": "requests to act in the world: book, buy, order, send, call",
}

LANGUAGES = {
    "el": "Greek, written in the Greek alphabet",
    "greeklish": "Greek written in Latin letters (Greeklish), as many Greek users type",
    "el_en": "Greek mixed with English words (code switching)",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
}

NOISE = {
    "typos": "all lowercase, several spelling mistakes, no punctuation",
    "long": "long and rambling, 50 to 110 words, with background about the user's project",
    "terse": "telegraphic, as few words as possible",
    "shouty": "ALL CAPS or with emojis and exclamation marks",
}

CONTESTED = {
    "metadata": (
        ["dataset_search", "question"],
        "questions about a dataset's metadata: licence, publisher, size, period covered, file "
        "format, last update (e.g. 'what licence does ESCO have?')",
    ),
    "general_knowledge": (
        ["question", "out_of_scope"],
        "general knowledge questions not clearly tied to data: history, science, definitions "
        "(e.g. 'when did the French revolution start?')",
    ),
    "learning_material": (
        ["question", "dataset_search"],
        "requests for learning resources on a maths topic: videos, exercises, notes",
    ),
    "mixed": (
        ["question", "dataset_search"],
        "asks both to find datasets and to answer something in the same input",
    ),
    "forecast": (
        ["question", "out_of_scope"],
        "predictions about the future or current conditions (e.g. 'will it rain in Athens "
        "tomorrow?')",
    ),
    "methodology": (
        ["out_of_scope", "ambiguous", "question"],
        "asks for advice on research method or analysis approach (e.g. 'which statistical "
        "test should I use to compare two regions?')",
    ),
}

CONTEXT_RECIPES = {
    "question": "a follow-up asking for more answers about the datasets already in use "
    "(another period, place, breakdown, chart of the previous result)",
    "dataset_search": "a follow-up asking for other or additional datasets",
    "out_of_scope": "a closing remark or small talk (thanks, that's all, great job)",
    "ambiguous": "a follow-up that is only a new topic word or two",
}

GENERATOR_PROMPT = """\
You are helping build a test set for the search box of DataGEMS, a European research-data
platform. Users type one input in a single search box on the home page.

Data the platform hosts includes: {domains}

Write {n} distinct inputs that real users could type, all matching this target.
INTENT: {intent}
STYLE: {style}
LANGUAGE: {language}

Requirements:
- Every input must clearly fit the INTENT and STYLE.
- Vary the users (PhD students, teachers, journalists, policy analysts, data scientists,
  curious citizens), the length and the wording. Do not start inputs the same way.
- Use concrete places, years, variables and named sources where natural; do not only reuse
  the examples above.
- Output only the inputs themselves.
Return JSON: {{"queries": ["..."]}}
"""

CONTEXT_PROMPT = """\
You are helping build a test set for the chat of DataGEMS, a European research-data platform.
Data the platform hosts includes: {domains}

Write {n} short conversations. Each has 1 or 2 earlier user messages (questions answered from
data, or dataset searches) and then the user's next input, which must be: {target}
Vary topics across the hosted data. Use English.
Return JSON: {{"items": [{{"history": ["..."], "query": "..."}}]}}
"""

JUDGE_PROMPT = """\
You are annotating a benchmark for DataGEMS, a research-data platform. Users type into a single
search box. For each input, decide the single best way for the platform to respond:

dataset_search: show a list of matching datasets. Right when the user is looking for data,
  datasets, sources or corpora, wants to know what data exists, wants to download or access
  data, or wants datasets similar to another dataset.
question: compute or look up an answer inside the data and show it (a value, table, chart,
  records, comparison, trend). Right when the user wants a fact, statistic or analysis result,
  including commands ("plot ...") and keyword phrases that clearly ask for a value.
ambiguous: the input is only a topic, keywords or a theme, and it is genuinely unclear
  whether the user wants datasets or an answer; the platform should ask them.
out_of_scope: not a request for data or for data-derived answers: greetings, small talk,
  feelings, creative writing, general assistant tasks, help with the website or account,
  nonsense, real-world actions, or attempts to manipulate the system.

Judge by what the user wants returned, not by which words appear ("data" can appear in a
question). Inputs can be in any language and contain typos. When an input has a history of
earlier messages, it is a follow-up in the same conversation; use the history.

Label every item. Return JSON: {"labels": [{"id": "...", "label": "...", "confidence": 0.0}]}
"""

QUERIES_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}
CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "history": {"type": "array", "items": {"type": "string"}},
                    "query": {"type": "string"},
                },
                "required": ["history", "query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
LABELS_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string", "enum": list(INTENTS)},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "label", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def recipes() -> list[dict]:
    """Every generation call: what to ask for and how the result is labelled."""
    out: list[dict] = []
    en = "English"
    for intent in ("dataset_search", "question", "ambiguous"):
        for slice_name, style in SLICES[intent].items():
            for domain in DOMAINS:
                n = {"dataset_search": 4, "question": 3, "ambiguous": 4}[intent]
                out.append(
                    dict(
                        intent=intent,
                        slice=slice_name,
                        style=style,
                        domain=domain,
                        language="en",
                        language_desc=en,
                        n=n,
                    )
                )
    for slice_name, (domain, style) in DOMAIN_SPECIFIC_QUESTION_SLICES.items():
        out.append(
            dict(
                intent="question",
                slice=slice_name,
                style=style,
                domain=domain,
                language="en",
                language_desc=en,
                n=12,
            )
        )
    for slice_name, style in OUT_OF_SCOPE_SLICES.items():
        out.append(
            dict(
                intent="out_of_scope",
                slice=slice_name,
                style=style,
                domain=None,
                language="en",
                language_desc=en,
                n=6,
            )
        )
    for lang, desc in LANGUAGES.items():
        for intent in INTENTS:
            style = "any natural phrasing" if intent != "out_of_scope" else "any kind"
            out.append(
                dict(
                    intent=intent,
                    slice="multilingual",
                    style=style,
                    domain=None,
                    language=lang,
                    language_desc=desc,
                    n=5,
                )
            )
    for noise, style in NOISE.items():
        for intent in INTENTS:
            out.append(
                dict(
                    intent=intent,
                    slice=f"noise_{noise}",
                    style=style,
                    domain=None,
                    language="en",
                    language_desc=en,
                    n=6,
                )
            )
    for name, (acceptable, style) in CONTESTED.items():
        out.append(
            dict(
                intent=acceptable[0],
                acceptable=acceptable,
                slice=f"contested_{name}",
                style=style,
                domain=None,
                language="en",
                language_desc=en,
                n=8,
            )
        )
    for intent, target in CONTEXT_RECIPES.items():
        out.append(
            dict(
                intent=intent,
                slice="follow_up",
                style=target,
                domain=None,
                language="en",
                language_desc=en,
                n=10,
                context=True,
            )
        )
    for i, recipe in enumerate(out):
        recipe["recipe_id"] = i
        recipe["generator"] = GENERATORS[i % len(GENERATORS)]
    return out


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\W_]+", " ", text).strip()


def item_id(query: str, history: list[str] | None) -> str:
    key = normalize(query) + "|" + "|".join(normalize(h) for h in history or [])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_client() -> ScayleClient:
    s = Settings.from_env()
    if not s.scayle_username:
        sys.exit("SCAYLE_USERNAME is not set; run with --env-file .env")
    return ScayleClient(
        s.scayle_base_url,
        s.scayle_username,
        s.scayle_password,
        verify_ssl=s.scayle_verify_ssl,
        timeout=180,
    )


async def call_json(
    client: ScayleClient,
    model: str,
    prompt: str,
    schema: dict,
    temperature: float,
    system: str | None = None,
) -> dict:
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": prompt})
    for attempt in range(3):
        try:
            content = await client.chat(
                model,
                messages,
                temperature=temperature,
                max_tokens=8000,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "out", "schema": schema, "strict": True},
                },
            )
            return json.loads(content)
        except (ScayleError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise
            print(f"  retry {model}: {str(exc)[:120]}", file=sys.stderr)
            await asyncio.sleep(2 + attempt * 3)
    raise AssertionError("unreachable")


async def generate(concurrency: int) -> None:
    done = {row["recipe_id"] for row in read_jsonl(GENERATED)}
    todo = [r for r in recipes() if r["recipe_id"] not in done]
    print(f"{len(todo)} generation calls to make ({len(done)} already done)")
    client = make_client()
    semaphore = asyncio.Semaphore(concurrency)
    rng = random.Random(7)

    async def run(recipe: dict) -> None:
        domains = (
            DOMAINS[recipe["domain"]]
            if recipe["domain"]
            else "; ".join(v for k, v in DOMAINS.items() if k != "off_catalog")
        )
        async with semaphore:
            try:
                if recipe.get("context"):
                    prompt = CONTEXT_PROMPT.format(
                        domains=domains, n=recipe["n"], target=recipe["style"]
                    )
                    data = await call_json(client, recipe["generator"], prompt, CONTEXT_SCHEMA, 1.0)
                    items = [(i["query"], i["history"]) for i in data["items"]]
                else:
                    prompt = GENERATOR_PROMPT.format(
                        domains=domains,
                        n=recipe["n"],
                        intent=INTENTS[recipe["intent"]],
                        style=recipe["style"],
                        language=recipe["language_desc"],
                    )
                    data = await call_json(client, recipe["generator"], prompt, QUERIES_SCHEMA, 1.0)
                    items = [(q, None) for q in data["queries"]]
            except Exception as exc:  # keep going; the recipe is retried on the next run
                print(f"  recipe {recipe['recipe_id']} failed: {str(exc)[:160]}", file=sys.stderr)
                return
        rows = []
        for query, history in items:
            query = query.strip()
            if not query:
                continue
            context = None
            if history is not None:
                # Questions and searches follow from datasets already in use
                n_datasets = 0 if recipe["intent"] == "out_of_scope" else rng.randint(1, 3)
                context = {
                    "history": [h.strip() for h in history if h.strip()],
                    "dataset_ids": [
                        str(uuid.UUID(int=rng.getrandbits(128), version=4))
                        for _ in range(n_datasets)
                    ],
                }
            rows.append(
                {
                    "id": item_id(query, history),
                    "query": query,
                    "context": context,
                    "intent": recipe["intent"],
                    "acceptable": recipe.get("acceptable"),
                    "slice": recipe["slice"],
                    "domain": recipe["domain"],
                    "language": recipe["language"],
                    "generator": recipe["generator"],
                    "recipe_id": recipe["recipe_id"],
                }
            )
        append_jsonl(GENERATED, rows)
        print(
            f"  recipe {recipe['recipe_id']:3d} {recipe['intent']:14s} {recipe['slice']:22s} "
            f"{recipe['language']:9s} -> {len(rows)}"
        )

    try:
        await asyncio.gather(*(run(r) for r in todo))
    finally:
        await client.aclose()


def unique_generated() -> list[dict]:
    """Generated rows without duplicates or copies of the prompt's examples."""
    prompt = yaml.safe_load((PROMPTS_DIR / "intent_v2.yaml").read_text("utf-8"))
    banned = {normalize(e["query"]) for e in prompt["examples"]}
    seen: set[str] = set()
    rows = []
    for row in read_jsonl(GENERATED):
        if row["id"] in seen or normalize(row["query"]) in banned:
            continue
        seen.add(row["id"])
        rows.append(row)
    return rows


async def judge(concurrency: int) -> None:
    rows = unique_generated()
    done = {(j["id"], j["judge"]) for j in read_jsonl(JUDGED)}
    client = make_client()
    semaphore = asyncio.Semaphore(concurrency)
    batches = []
    for model in JUDGES:
        pending = [r for r in rows if (r["id"], model) not in done]
        random.Random(11).shuffle(pending)  # mix intents within a batch
        batches += [
            (model, pending[i : i + JUDGE_BATCH]) for i in range(0, len(pending), JUDGE_BATCH)
        ]
    print(f"{len(batches)} judge calls to make")

    async def run(model: str, batch: list[dict]) -> None:
        items = [
            {
                "id": r["id"],
                "input": r["query"],
                **({"history": r["context"]["history"]} if r.get("context") else {}),
            }
            for r in batch
        ]
        prompt = "Items:\n" + json.dumps(items, ensure_ascii=False, indent=1)
        async with semaphore:
            try:
                data = await call_json(
                    client, model, prompt, LABELS_SCHEMA, 0.0, system=JUDGE_PROMPT
                )
            except Exception as exc:
                print(f"  judge {model} failed: {str(exc)[:160]}", file=sys.stderr)
                return
        wanted = {r["id"] for r in batch}
        out = [
            {
                "id": lab["id"],
                "judge": model,
                "label": lab["label"],
                "confidence": lab["confidence"],
            }
            for lab in data["labels"]
            if lab["id"] in wanted
        ]
        append_jsonl(JUDGED, out)

    try:
        await asyncio.gather(*(run(m, b) for m, b in batches))
    finally:
        await client.aclose()


def finalize() -> None:
    rows = unique_generated()
    judged: dict[str, dict[str, str]] = {}
    for j in read_jsonl(JUDGED):
        judged.setdefault(j["id"], {})[j["judge"]] = j["label"]
    overrides = yaml.safe_load(OVERRIDES.read_text("utf-8")) if OVERRIDES.exists() else {}
    overrides = overrides or {}

    benchmark, review = [], []
    stats = {"accepted": 0, "overridden": 0, "dropped": 0, "pending_review": 0, "unjudged": 0}
    for row in rows:
        labels = judged.get(row["id"], {})
        row["judges"] = labels
        decision = overrides.get(row["id"])
        if decision is not None:
            if decision.get("drop"):
                stats["dropped"] += 1
                continue
            row["intent"] = decision.get("intent", row["intent"])
            row["acceptable"] = decision.get("acceptable", row.get("acceptable"))
            row["review_note"] = decision.get("note")
            stats["overridden"] += 1
            benchmark.append(row)
            continue
        if len(labels) < len(JUDGES):
            stats["unjudged"] += 1
            continue
        contested = row.get("acceptable") is not None
        if contested or all(label == row["intent"] for label in labels.values()):
            stats["accepted"] += 1
            benchmark.append(row)
        else:
            stats["pending_review"] += 1
            review.append(row)

    keys = [
        "id",
        "query",
        "context",
        "intent",
        "acceptable",
        "slice",
        "domain",
        "language",
        "generator",
        "judges",
        "review_note",
    ]
    BENCHMARK.write_text(
        "".join(
            json.dumps({k: row.get(k) for k in keys}, ensure_ascii=False) + "\n"
            for row in benchmark
        ),
        "utf-8",
    )
    REVIEW.write_text(
        "".join(
            json.dumps({k: row.get(k) for k in keys}, ensure_ascii=False) + "\n" for row in review
        ),
        "utf-8",
    )
    print(json.dumps(stats))
    print(f"{len(benchmark)} items -> {BENCHMARK}")
    print(f"{len(review)} items need a decision in overrides.yaml -> {REVIEW}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["generate", "judge", "finalize", "plan"])
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    setup_logging(json_logs=False, log_level="WARNING")
    if args.stage == "plan":
        planned = recipes()
        print(f"{len(planned)} recipes, {sum(r['n'] for r in planned)} inputs requested")
    elif args.stage == "generate":
        asyncio.run(generate(args.concurrency))
    elif args.stage == "judge":
        asyncio.run(judge(args.concurrency))
    else:
        finalize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
