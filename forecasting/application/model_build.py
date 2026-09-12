"""Shared market-model build operation for forecast entrypoints."""

from __future__ import annotations

from typing import Any


def link_built_model(ledger: Any, question_id: str, model_id: str) -> None:
    """Atomically attach an existing build; retrying does not rebuild the model."""
    with ledger.transaction(immediate=True):
        model = ledger.get_market_model(model_id)
        spec = dict(model.get("spec") or {})
        spec["forecast_question_id"] = question_id
        ledger.update_market_model_spec(model_id, spec)
        ledger.link_question_market_model(question_id, model_id)


def build_model(args: dict[str, Any], ledger: Any) -> dict[str, Any]:
    from forecasting import market_model as MM

    q_id = args.get("question_id")
    linked_question = None
    question_text = (args.get("question") or "").strip()
    outcome_type = args.get("outcome_type")
    if q_id:
        linked_question = ledger.get_question(q_id)
        if not question_text:
            title = getattr(linked_question, "title", "") or ""
            desc = getattr(linked_question, "description", "") or ""
            question_text = (f"{title}\n\n{desc}".strip()) or title
        if not outcome_type:
            outcome_type = getattr(
                getattr(linked_question, "outcome_space", None), "type", None
            )
    if not question_text:
        return {
            "success": False,
            "error": "build_model requires 'question' (or a 'question_id' to derive it from)",
        }

    mparams = dict(args.get("params") or {})
    if outcome_type and "outcome_type" not in mparams:
        mparams["outcome_type"] = outcome_type
    for k in (
        "depth",
        "analysis_type",
        "tickers",
        "horizon",
        "target_year",
        "assumptions",
        "model",
        "provider",
    ):
        if args.get(k) is not None and k not in mparams:
            mparams[k] = args.get(k)

    # Agents sometimes put a quantitative METHOD in the LLM `model` field.
    # Keep those namespaces separate so an identifier such as
    # `correlated_regime_switching_monte_carlo` is never sent to an API.
    llm_model = str(mparams.get("model") or "").strip()
    method_markers = (
        "monte_carlo",
        "regime_switch",
        "simulation",
        "timeseries",
        "loglinear",
    )
    if llm_model and any(marker in llm_model.lower() for marker in method_markers):
        mparams.setdefault("analysis_type", llm_model)
        mparams.pop("model", None)

    recommendation = MM.recommend_model_family(outcome_type, question_text)
    out = MM.build_market_model(
        question_text, mparams, ledger=ledger, runtime=args.get("runtime")
    )
    model_id = out.get("model_id")

    result = dict(
        success=True,
        model_id=model_id,
        version=out.get("version"),
        model_status=out.get("status"),
        question_id=q_id,
        recommended_model=recommendation,
    )
    if q_id and model_id:
        try:
            link_built_model(ledger, q_id, model_id)
        except Exception as exc:
            # Keep the durable build addressable without claiming the link worked.
            result.update(
                success=False,
                link_status="failed",
                error=f"Model {model_id} was built but linking failed: {exc}",
            )
        else:
            result["link_status"] = "completed"
    return result
