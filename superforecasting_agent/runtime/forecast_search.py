"""Forecast desk search ranking, result formatting, and reference parsing."""

import re


def _forecast_search_normalize(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_ -]+", " ", str(value or "").lower())).strip()


def _forecast_dashboard_rows(cls, summary: dict) -> list[tuple[int, dict]]:
    rows: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for index, row in enumerate(summary.get("questions") or [], start=1):
        row_id = str(row.get("id") or "")
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        rows.append((index, row))
    for row in summary.get("review_queue") or []:
        row_id = str(row.get("id") or "")
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        rows.append((len(rows) + 1, row))
    return rows


def _forecast_search_matches(cls, summary: dict, query: str, *, limit: int = 12) -> list[dict]:
    full_query = cls._forecast_search_normalize(query)
    tokens = [token for token in full_query.split() if len(token) >= 2]
    if not full_query:
        return []

    matches: list[dict] = []
    for index, row in cls._forecast_dashboard_rows(summary):
        row_id = str(row.get("id") or "")
        short_id = re.sub(r"^fq_", "", row_id)[:8]
        title = str(row.get("title") or "")
        domain = str(row.get("domain") or "")
        raw_topics = row.get("topics") or []
        topics = raw_topics if isinstance(raw_topics, str) else " ".join(str(topic) for topic in raw_topics)
        status = str(row.get("status") or "")
        rationale = str(row.get("latest_rationale") or "")
        evidence = " ".join(
            [
                str(row.get("latest_evidence_claim") or ""),
                str(row.get("latest_evidence_summary") or ""),
            ]
        )
        text = cls._forecast_search_normalize(
            " ".join([row_id, short_id, title, domain, topics, status, rationale, evidence])
        )
        title_text = cls._forecast_search_normalize(title)
        rationale_text = cls._forecast_search_normalize(rationale)
        evidence_text = cls._forecast_search_normalize(evidence)
        score = 0

        if cls._forecast_search_normalize(row_id) == full_query or cls._forecast_search_normalize(short_id) == full_query:
            score += 40
        elif full_query in cls._forecast_search_normalize(row_id) or full_query in cls._forecast_search_normalize(short_id):
            score += 24
        if full_query in title_text:
            score += 14
        if domain and full_query in cls._forecast_search_normalize(domain):
            score += 8
        if topics and full_query in cls._forecast_search_normalize(topics):
            score += 8
        if rationale and full_query in rationale_text:
            score += 6
        if evidence and full_query in evidence_text:
            score += 6
        for token in tokens:
            if token not in text:
                continue
            score += 4 if token in title_text else 2
        if tokens and all(token in text for token in tokens):
            score += 6

        if score > 0:
            matches.append({"index": index, "row": row, "score": score})

    matches.sort(key=lambda item: (-int(item["score"]), int(item["index"])))
    return matches[: max(limit, 0)]


def _print_forecast_search(cls, summary: dict, query: str) -> None:
    from forecasting.dashboard import (
        format_confidence,
        format_delta,
        format_freshness,
        format_probability,
        question_status,
        short_date,
    )

    matches = cls._forecast_search_matches(summary, query, limit=12)
    print("FORECAST SEARCH")
    print(f"query: {query}")
    print(f"matches: {len(matches)}")
    if not matches:
        print("No matching active forecasts or review-queue items. Try fewer words, a topic, or a domain.")
        return

    print(
        f"{'Rank':<5} {'ID':<14} {'P(now)':<12} {'Delta':<8} {'Freshness':<12} "
        f"{'Close':<12} {'Conf':<6} {'Ev':>3} {'Status':<12} Question"
    )
    for rank, match in enumerate(matches, start=1):
        row = match["row"]
        row_id = str(row.get("id") or "")
        print(
            f"{rank:<5} "
            f"{row_id:<14.14} "
            f"{format_probability(row.get('probability')):<12} "
            f"{format_delta(row.get('delta')):<8} "
            f"{format_freshness(row.get('as_of')):<12} "
            f"{short_date(row.get('close_time')):<12} "
            f"{format_confidence(row.get('confidence')):<6} "
            f"{int(row.get('evidence_count') or 0):>3} "
            f"{question_status(row):<12} "
            f"{row.get('title') or ''}"
        )
    print("")
    print("Open one match with /open <row|id|words>.")
    print("Append evidence with /note <row|words> -- <evidence>.")
    print("Append an update with /revise <row|words> -- --probability <p> --rationale <why>.")


def _split_forecast_ref_and_rest(raw_arg: str) -> tuple[str, str]:
    separator = raw_arg.find(" -- ")
    if separator >= 0:
        return raw_arg[:separator].strip(), raw_arg[separator + 4:].strip()
    parts = raw_arg.split(maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) > 1 else (raw_arg.strip(), "")
