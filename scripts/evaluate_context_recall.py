#!/usr/bin/env python3
"""Compare synthetic forecast recall with uncompacted and lossy controls.

Default mode measures exact fact retention, not model reasoning quality. Explicit
provider/model arguments additionally ask that model to recall each fact from
all three contexts. Nothing reads or writes a live forecast ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from agent.compaction_recall import build_recall_index

FACTS = {
    "question_id": "fq_ab120034ef56",
    "forecast_id": "fs_120034abcdef",
    "canonical_url": "https://www.bls.gov/news.release/cpi.htm",
    "observation_period": "2026-08",
    "entity": "CPI-U US city average all items",
    "units": "percent month over month seasonally adjusted",
    "revision_policy": "first published release",
    "unresolved_assumptions": "Seasonal-factor revisions have not been ruled out.",
}


def contexts() -> dict[str, str]:
    messages = [
        {
            "role": "user",
            "content": "Research this synthetic question; do not resolve it.",
        },
        {
            "role": "tool",
            "tool_call_id": "fixture-source-1",
            "content": json.dumps(FACTS),
        },
        {
            "role": "assistant",
            "content": "Several inflation measurements were investigated. " * 100,
        },
    ]
    lossy = "Earlier research concerned an inflation forecast. Verify the exact source and measurement before settlement."
    return {
        "uncompacted_control": json.dumps(messages),
        "lossy_summary_control": lossy,
        "lossy_summary_with_exact_index": lossy + build_recall_index(messages),
    }


def evaluate(provider: str | None = None, model: str | None = None) -> dict[str, Any]:
    if bool(provider) != bool(model):
        raise ValueError("Provider and model must be specified together")
    variants = contexts()
    report: dict[str, Any] = {
        "schema_version": 1,
        "fixture_sha256": hashlib.sha256(
            json.dumps(FACTS, sort_keys=True).encode()
        ).hexdigest(),
        "mode": "model_recall" if model else "mechanical_retention",
        "requested_provider": provider,
        "requested_model": model,
        "limitations": "One synthetic fixture; retention is not evidence of improved live forecasting or general recall.",
        "policies": {},
    }
    for policy, context in variants.items():
        retained = {key: value in context for key, value in FACTS.items()}
        result: dict[str, Any] = {
            "characters": len(context),
            "exact_retention": retained,
        }
        if model and provider:
            from agent.auxiliary_client import call_llm

            answers = {}
            for key, expected in FACTS.items():
                # No gold answer or another policy's response is sent to the model.
                response = call_llm(
                    provider=provider,
                    model=model,
                    temperature=0,
                    max_tokens=200,
                    timeout=60,
                    messages=[
                        {
                            "role": "system",
                            "content": "Answer only from the quoted historical context. Return the exact requested value, or UNKNOWN if absent. Do not invent missing measurements.",
                        },
                        {
                            "role": "user",
                            "content": f"Historical context:\n{context}\n\nWhat is the exact {key}?",
                        },
                    ],
                )
                actual = response.choices[0].message.content
                answers[key] = {
                    "answer": actual,
                    "exact_match": isinstance(actual, str)
                    and actual.strip() == expected,
                    "reported_model": getattr(response, "model", None),
                }
            result["recall"] = answers
        report["policies"][policy] = result
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.provider) != bool(args.model):
        parser.error("--provider and --model must be specified together")
    report = evaluate(args.provider, args.model)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    report["code_commit"] = (
        revision.stdout.strip() if revision.returncode == 0 else None
    )
    report["implementation_sha256"] = hashlib.sha256(
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("agent/compaction_recall.py")
        .read_bytes()
    ).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {report['mode']} report to {args.output}")


if __name__ == "__main__":
    main()
