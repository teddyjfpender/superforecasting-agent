"""Built-in benchmark datasets for replay and calibration checks."""

from __future__ import annotations

import csv
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from typing import Any

from forecasting.benchmark_evidence import build_benchmark_evidence_profile


_MINI_BINARY_CASES: list[dict[str, Any]] = [
    {
        "id": "mini-001",
        "title": "Will the central bank cut rates at the June meeting?",
        "resolution_criteria": "Resolved yes if the target policy rate is lowered at the June meeting.",
        "domain": "macro",
        "topics": ["rates"],
        "as_of": "2024-05-15T00:00:00Z",
        "close_time": "2024-06-12T00:00:00Z",
        "probability": 0.58,
        "base_rate": 0.52,
        "outcome": "no",
        "evidence": [
            {"note": "Inflation surprise was above consensus.", "available_at": "2024-05-10T12:00:00Z", "stance": "decreases"},
            {"note": "Labor market softened modestly.", "available_at": "2024-05-14T12:00:00Z", "stance": "increases"},
        ],
    },
    {
        "id": "mini-002",
        "title": "Will the bill pass committee before recess?",
        "resolution_criteria": "Resolved yes if the committee reports the bill before the summer recess.",
        "domain": "policy",
        "topics": ["legislation"],
        "as_of": "2024-06-01T00:00:00Z",
        "close_time": "2024-07-15T00:00:00Z",
        "probability": 0.64,
        "base_rate": 0.48,
        "outcome": "yes",
        "evidence": [
            {"note": "Sponsor added two swing committee members.", "available_at": "2024-05-28T00:00:00Z", "stance": "increases"},
        ],
    },
    {
        "id": "mini-003",
        "title": "Will company Y default on its September coupon?",
        "resolution_criteria": "Resolved yes if company Y misses or restructures the September coupon payment.",
        "domain": "credit",
        "topics": ["default"],
        "as_of": "2024-08-01T00:00:00Z",
        "close_time": "2024-09-30T00:00:00Z",
        "probability": 0.31,
        "base_rate": 0.24,
        "outcome": "no",
        "evidence": [
            {"note": "Liquidity runway improved after asset sale.", "available_at": "2024-07-25T00:00:00Z", "stance": "decreases"},
        ],
    },
    {
        "id": "mini-004",
        "title": "Will the regulator approve the therapy by PDUFA?",
        "resolution_criteria": "Resolved yes if the regulator approves the therapy on or before the PDUFA date.",
        "domain": "biotech",
        "topics": ["regulatory"],
        "as_of": "2024-03-01T00:00:00Z",
        "close_time": "2024-05-01T00:00:00Z",
        "probability": 0.72,
        "base_rate": 0.68,
        "outcome": "yes",
        "evidence": [
            {"note": "Advisory committee vote was favorable.", "available_at": "2024-02-20T00:00:00Z", "stance": "increases"},
        ],
    },
    {
        "id": "mini-005",
        "title": "Will unemployment exceed 5 percent by year end?",
        "resolution_criteria": "Resolved yes if the official unemployment rate is above 5 percent in the final annual release.",
        "domain": "macro",
        "topics": ["labor"],
        "as_of": "2024-09-01T00:00:00Z",
        "close_time": "2024-12-31T00:00:00Z",
        "probability": 0.27,
        "base_rate": 0.22,
        "outcome": "no",
        "evidence": [
            {"note": "Payroll growth remained positive.", "available_at": "2024-08-30T12:00:00Z", "stance": "decreases"},
        ],
    },
]


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _synthetic_binary_cases(count: int = 100) -> list[dict[str, Any]]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    domains = ["macro", "policy", "credit", "biotech", "technology"]
    topics = ["rates", "legislation", "default", "regulatory", "adoption"]
    cases = []
    for index in range(count):
        as_of = start + timedelta(days=index * 3)
        close_time = as_of + timedelta(days=45 + (index % 20))
        outcome_yes = index % 5 in {1, 2, 4}
        probability = 0.28 + ((index * 17) % 50) / 100
        base_rate = 0.35 + ((index * 11) % 30) / 100
        domain = domains[index % len(domains)]
        topic = topics[index % len(topics)]
        cases.append(
            {
                "id": f"synthetic-100-{index + 1:03d}",
                "title": f"Will synthetic benchmark event {index + 1} resolve yes?",
                "resolution_criteria": (
                    "Resolved by the synthetic benchmark fixture outcome for "
                    f"case {index + 1}."
                ),
                "domain": domain,
                "topics": [topic],
                "as_of": _iso(as_of),
                "close_time": _iso(close_time),
                "probability": round(probability, 2),
                "base_rate": round(base_rate, 2),
                "outcome": "yes" if outcome_yes else "no",
                "evidence": [
                    {
                        "note": f"Synthetic pre-cutoff evidence for case {index + 1}.",
                        "available_at": _iso(as_of - timedelta(days=2)),
                        "stance": "increases" if outcome_yes else "decreases",
                    }
                ],
            }
        )
    return cases


_SYNTHETIC_100_BINARY_CASES = _synthetic_binary_cases()


def _heldout_120_binary_cases() -> list[dict[str, Any]]:
    corpus_path = files("forecasting").joinpath("data", "heldout_120_binary.csv")
    rows = csv.DictReader(corpus_path.read_text(encoding="utf-8").splitlines())
    cases: list[dict[str, Any]] = []
    for row in rows:
        case_number = int(row["case_number"])
        domain = row["domain"]
        topic = row["topic"]
        as_of = row["as_of"]
        probability = float(row["probability"])
        base_rate = float(row["base_rate"])
        cases.append(
            {
                "id": f"heldout-120-{case_number:03d}",
                "title": f"Will held-out {domain} benchmark event {case_number:03d} resolve yes?",
                "resolution_criteria": (
                    "Resolved by the frozen held-out benchmark corpus outcome "
                    f"for case {case_number:03d}."
                ),
                "domain": domain,
                "topics": [topic],
                "as_of": as_of,
                "close_time": row["close_time"],
                "probability": probability,
                "base_rate": base_rate,
                "outcome": row["outcome"],
                "evidence": [
                    {
                        "note": (
                            f"Frozen pre-cutoff benchmark signal for held-out case {case_number:03d}."
                        ),
                        "available_at": as_of,
                        "stance": "increases" if probability >= base_rate else "decreases",
                    }
                ],
            }
        )
    return cases


_HELDOUT_120_BINARY_CASES = _heldout_120_binary_cases()


def _manifold_public_120_binary_cases() -> list[dict[str, Any]]:
    corpus_path = files("forecasting").joinpath("data", "manifold_public_120_binary.csv")
    rows = csv.DictReader(corpus_path.read_text(encoding="utf-8").splitlines())
    cases: list[dict[str, Any]] = []
    for row in rows:
        case_number = int(row["case_number"])
        probability = float(row["probability"])
        title = row["title"]
        url = row["url"]
        as_of = row["as_of"]
        cases.append(
            {
                "id": f"manifold-public-120-{case_number:03d}",
                "title": title,
                "description": row.get("description") or "",
                "resolution_criteria": (
                    "Resolved by the linked public Manifold market resolution."
                ),
                "resolution_source": url,
                "domain": "prediction_markets",
                "topics": ["manifold", "public_market"],
                "as_of": as_of,
                "simulated_forecast_time": as_of,
                "evidence_cutoff": as_of,
                "close_time": row["close_time"],
                "resolution_time": row["resolution_time"],
                "probability": probability,
                "outcome": row["outcome"],
                "evidence": [
                    {
                        "source": url,
                        "source_name": "Manifold",
                        "source_type": "adapter:manifold",
                        "url": url,
                        "claim": title,
                        "summary": row.get("description") or title,
                        "available_at": as_of,
                        "claim_type": "estimate",
                        "stance": "context",
                    }
                ],
                "baselines": [
                    {
                        "source": "manifold",
                        "baseline_type": "market",
                        "probability": probability,
                        "as_of": as_of,
                    },
                    {
                        "source": "auto",
                        "baseline_type": "naive_0_5",
                        "probability": 0.5,
                        "as_of": as_of,
                    }
                ],
                "notes": (
                    "Frozen public Manifold resolved-market corpus captured "
                    "for benchmark replay. Market probability is stored as both "
                    "the replayed forecast and an external baseline."
                ),
                "metadata": {
                    "source_dataset": "manifold_public_120_binary",
                    "external_id": row.get("external_id"),
                },
            }
        )
    return cases


_MANIFOLD_PUBLIC_120_BINARY_CASES = _manifold_public_120_binary_cases()


def _kalshi_public_120_binary_cases() -> list[dict[str, Any]]:
    corpus_path = files("forecasting").joinpath("data", "kalshi_public_120_binary.csv")
    rows = csv.DictReader(corpus_path.read_text(encoding="utf-8").splitlines())
    cases: list[dict[str, Any]] = []
    for row in rows:
        case_number = int(row["case_number"])
        probability = float(row["probability"])
        title = row["title"]
        url = row["url"]
        as_of = row["as_of"]
        cases.append(
            {
                "id": f"kalshi-public-120-{case_number:03d}",
                "title": title,
                "description": row.get("description") or "",
                "resolution_criteria": "Resolved by the linked public Kalshi market settlement.",
                "resolution_source": url,
                "domain": "prediction_markets",
                "topics": ["kalshi", "public_market"],
                "as_of": as_of,
                "simulated_forecast_time": as_of,
                "evidence_cutoff": as_of,
                "close_time": row["close_time"],
                "resolution_time": row["resolution_time"],
                "probability": probability,
                "outcome": row["outcome"],
                "evidence": [
                    {
                        "source": url,
                        "source_name": "Kalshi",
                        "source_type": "adapter:kalshi",
                        "url": url,
                        "claim": title,
                        "summary": row.get("description") or title,
                        "available_at": as_of,
                        "claim_type": "estimate",
                        "stance": "context",
                    }
                ],
                "baselines": [
                    {
                        "source": "kalshi",
                        "baseline_type": "market",
                        "probability": probability,
                        "as_of": as_of,
                    },
                    {
                        "source": "auto",
                        "baseline_type": "naive_0_5",
                        "probability": 0.5,
                        "as_of": as_of,
                    },
                ],
                "notes": (
                    "Frozen public Kalshi settled-market corpus captured for "
                    "benchmark replay. Market probability is stored as both the "
                    "replayed forecast and an external baseline."
                ),
                "metadata": {
                    "source_dataset": "kalshi_public_120_binary",
                    "external_id": row.get("external_id"),
                },
            }
        )
    return cases


_KALSHI_PUBLIC_120_BINARY_CASES = _kalshi_public_120_binary_cases()


BUILTIN_BENCHMARKS: dict[str, dict[str, Any]] = {
    "mini-binary": {
        "name": "mini-binary",
        "description": "Five resolved binary replay cases across macro, policy, credit, and biotech.",
        "case_count": len(_MINI_BINARY_CASES),
        "cases": _MINI_BINARY_CASES,
    },
    "synthetic-100-binary": {
        "name": "synthetic-100-binary",
        "description": "One hundred synthetic resolved binary cases for replay scale tests.",
        "case_count": len(_SYNTHETIC_100_BINARY_CASES),
        "cases": _SYNTHETIC_100_BINARY_CASES,
    },
    "heldout-120-binary": {
        "name": "heldout-120-binary",
        "description": "One hundred twenty frozen packaged binary cases for held-out replay checks.",
        "case_count": len(_HELDOUT_120_BINARY_CASES),
        "cases": _HELDOUT_120_BINARY_CASES,
    },
    "manifold-public-120-binary": {
        "name": "manifold-public-120-binary",
        "description": "One hundred twenty frozen public Manifold resolved binary markets.",
        "case_count": len(_MANIFOLD_PUBLIC_120_BINARY_CASES),
        "cases": _MANIFOLD_PUBLIC_120_BINARY_CASES,
    },
    "kalshi-public-120-binary": {
        "name": "kalshi-public-120-binary",
        "description": "One hundred twenty frozen public Kalshi settled binary markets.",
        "case_count": len(_KALSHI_PUBLIC_120_BINARY_CASES),
        "cases": _KALSHI_PUBLIC_120_BINARY_CASES,
    }
}


def list_builtin_benchmarks() -> list[dict[str, Any]]:
    return [
        {
            "name": row["name"],
            "description": row["description"],
            "case_count": row["case_count"],
            "benchmark_evidence": build_benchmark_evidence_profile(
                f"builtin:{row['name']}",
                row["cases"],
            ),
        }
        for row in BUILTIN_BENCHMARKS.values()
    ]


def load_builtin_benchmark(name: str) -> list[dict[str, Any]]:
    key = name.removeprefix("builtin:")
    if key not in BUILTIN_BENCHMARKS:
        raise KeyError(key)
    return deepcopy(BUILTIN_BENCHMARKS[key]["cases"])
