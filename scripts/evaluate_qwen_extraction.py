"""Measure the installed local Ollama model against the Qwen extraction fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from concordia.stability.nl_schema import enum_only_schema, validate_enum_response

THRESHOLDS = {
    "ship_exact_match_at_least": 0.90,
    "narrow_and_remeasure_min": 0.70,
    "narrow_and_remeasure_max_exclusive": 0.90,
}


def digits_in_fields(response: object) -> bool:
    return not isinstance(response, dict) or any(
        bool(re.search(r"\d", str(value))) for value in response.values()
    )


def call_model(
    host: str, model: str, schema: dict[str, Any], utterance: str
) -> tuple[dict[str, Any], str, float]:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "seed": 1729, "num_predict": 64},
        "messages": [
            {
                "role": "system",
                "content": "Return only enum JSON. Never emit digits in any value.",
            },
            {"role": "user", "content": utterance},
        ],
    }
    started = time.perf_counter()
    response = httpx.post(f"{host}/api/chat", json=payload, timeout=120.0)
    response.raise_for_status()
    outer = response.json()
    raw = str(outer.get("message", {}).get("content", ""))
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("model JSON was not an object")
    return parsed, raw, time.perf_counter() - started


def evaluate(fixture_path: Path, output_path: Path, host: str, model: str) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    schema = enum_only_schema(["stability", "structure", "constraints", "none"])
    fixture_digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    tags = httpx.get(f"{host}/api/tags", timeout=10.0)
    tags.raise_for_status()
    result: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "fixture": str(fixture_path),
        "fixture_sha256": fixture_digest,
        "thresholds": THRESHOLDS,
        "model_requested": model,
        "host": host,
        "schema": schema,
        "confidence_low_proxy": fixture["confidence_low_proxy"],
        "ollama_tags_raw": tags.text,
        "items": [],
    }
    for item in fixture["items"]:
        record: dict[str, Any] = {
            "id": item["id"],
            "category": item["category"],
            "utterance": item["utterance"],
            "expected": item["expected"],
        }
        try:
            actual, raw, latency = call_model(host, model, schema, item["utterance"])
            validation_error: str | None = None
            try:
                validate_enum_response(actual, schema)
            except Exception as error:
                validation_error = str(error)
            record.update({
                "actual": actual,
                "raw": raw,
                "latency_seconds": latency,
                "valid": validation_error is None,
                "exact_match": validation_error is None and actual == item["expected"],
                "digits_in_model_fields": digits_in_fields(actual),
                "validation_error": validation_error,
            })
        except Exception as error:
            record.update({"error": f"{type(error).__name__}: {error}", "exact_match": False})
        result["items"].append(record)
    completed = [item for item in result["items"] if "actual" in item]
    exact = [item for item in completed if item["exact_match"]]
    categories: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "exact": 0})
    for item in completed:
        category = str(item["category"])
        categories[category]["n"] += 1
        categories[category]["exact"] += int(bool(item["exact_match"]))
    underspecified = [item for item in completed if item["category"] == "underspecified"]
    low_proxy = [
        item for item in underspecified
        if item.get("actual", {}).get("evidence") == "insufficient"
    ]
    rate = len(exact) / len(completed) if completed else None
    result["summary"] = {
        "attempted": len(result["items"]),
        "completed": len(completed),
        "exact_match_rate": rate,
        "per_category": dict(categories),
        "underspecified_low_proxy_rate": (
            len(low_proxy) / len(underspecified) if underspecified else None
        ),
        "latency_seconds": {
            "mean": sum(float(item["latency_seconds"]) for item in completed) / len(completed)
            if completed else None,
            "min": min((float(item["latency_seconds"]) for item in completed), default=None),
            "max": max((float(item["latency_seconds"]) for item in completed), default=None),
        },
        "digit_violations": [
            item["id"] for item in completed if item.get("digits_in_model_fields")
        ],
        "failures": [item for item in result["items"] if not item.get("exact_match", False)],
        "decision": (
            "ship" if rate is not None and rate >= THRESHOLDS["ship_exact_match_at_least"]
            else "narrow_and_remeasure"
            if rate is not None and rate >= THRESHOLDS["narrow_and_remeasure_min"]
            else "upgrade"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("evals/qwen_extraction_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("results/qwen_extraction_v1.json"))
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:1.7b")
    args = parser.parse_args()
    result = evaluate(args.fixture, args.output, args.host, args.model)
    print(json.dumps({"summary": result["summary"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
