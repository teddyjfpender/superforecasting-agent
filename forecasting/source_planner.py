"""Forecast-aware evidence source planning."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from forecasting.models import ForecastQuestion


@dataclass(frozen=True)
class SourceRecommendation:
    id: str
    label: str
    source_type: str
    source: str
    role: str
    priority: str
    rationale: str
    watch_source: str | None = None
    import_command: str | None = None
    watch_command: str | None = None
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    materiality: str = "medium"
    requires_user_source: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "source_type": self.source_type,
            "source": self.source,
            "role": self.role,
            "priority": self.priority,
            "rationale": self.rationale,
            "watch_source": self.watch_source,
            "import_command": self.import_command,
            "watch_command": self.watch_command,
            "keywords": list(self.keywords),
            "exclude_keywords": list(self.exclude_keywords),
            "materiality": self.materiality,
            "requires_user_source": self.requires_user_source,
        }


_STOPWORDS = {
    "about",
    "after",
    "before",
    "being",
    "could",
    "during",
    "forecast",
    "from",
    "have",
    "into",
    "over",
    "question",
    "resolved",
    "than",
    "that",
    "their",
    "there",
    "this",
    "will",
    "with",
    "would",
}

_CPI_KEYWORDS = [
    "CPI",
    "inflation",
    "consumer prices",
    "gasoline",
    "energy",
    "oil",
    "shelter",
    "rent",
    "food",
    "tariff",
]


def plan_sources_for_question(
    question: ForecastQuestion,
    *,
    limit: int | None = None,
) -> list[SourceRecommendation]:
    """Return deterministic source recommendations for a forecast question.

    The planner deliberately does not fetch anything. It builds an initial
    checklist of measurable series, watched searches, and RSS/textual feeds so a
    forecaster can attach sources from question inception without bootstrapping
    the whole source map by hand.
    """

    text = _question_text(question)
    keywords = _keywords_for_question(question)
    recommendations: list[SourceRecommendation] = []

    if _looks_like_cpi_or_inflation(text):
        recommendations.extend(_cpi_macro_recommendations(question))
    elif _looks_like_macro(text):
        recommendations.extend(_macro_recommendations(question, keywords))

    if _looks_like_health(text):
        recommendations.extend(_health_recommendations(question, keywords))
    if _looks_like_technology(text):
        recommendations.extend(_technology_recommendations(question, keywords))
    if _looks_like_regulatory_or_legal(text):
        recommendations.extend(_regulatory_recommendations(question, keywords))
    if _looks_like_disaster_or_weather(text):
        recommendations.extend(_disaster_recommendations(question, keywords))
    if _looks_like_company_or_market(text):
        recommendations.extend(_company_market_recommendations(question, keywords))

    recommendations.extend(_generic_recommendations(question, keywords))

    deduped = _dedupe_recommendations(recommendations)
    if limit is not None:
        return deduped[: max(int(limit), 0)]
    return deduped


def _cpi_macro_recommendations(question: ForecastQuestion) -> list[SourceRecommendation]:
    qid = question.id
    gdelt_query = '(CPI OR inflation OR "consumer prices") (gasoline OR energy OR oil OR shelter OR rent OR tariff)'
    return [
        _adapter(
            qid,
            id="bls_cpi_all_items",
            label="BLS CPI-U all items",
            source_type="bls",
            source="CUUR0000SA0",
            role="official_measurement",
            priority="very_high",
            rationale="Official CPI series anchors resolution and backtests for U.S. CPI questions.",
        ),
        _adapter(
            qid,
            id="fred_cpi_index",
            label="FRED CPIAUCSL",
            source_type="fred",
            source="CPIAUCSL",
            role="quantitative_input",
            priority="high",
            rationale="FRED provides a convenient macro time series for CPI trend and revision checks.",
        ),
        _adapter(
            qid,
            id="eia_gasoline_prices",
            label="EIA weekly gasoline prices",
            source_type="eia",
            source="PET.EMM_EPM0_PTE_NUS_DPG.W",
            role="leading_indicator",
            priority="high",
            rationale="Gasoline prices are a fast-moving CPI component and can materially shift near-term inflation risk.",
        ),
        _adapter(
            qid,
            id="eia_wti_oil",
            label="EIA WTI crude oil",
            source_type="eia",
            source="PET.RWTC.W",
            role="leading_indicator",
            priority="medium",
            rationale="Oil shocks can affect gasoline, transportation, and inflation expectations before official CPI updates.",
        ),
        _rss(
            qid,
            id="bls_cpi_release_rss",
            label="BLS CPI release RSS",
            feed_url="https://www.bls.gov/feed/news_release/cpi.rss",
            role="official_textual_context",
            priority="high",
            rationale="Official release text captures methodology, component detail, and release timing around CPI updates.",
            keywords=_CPI_KEYWORDS,
            materiality="high",
        ),
        _adapter(
            qid,
            id="gdelt_cpi_energy_shelter",
            label="GDELT CPI energy shelter search",
            source_type="gdelt",
            source=gdelt_query,
            role="news_early_warning",
            priority="medium",
            rationale="Global news search can surface energy, shelter, tariff, or supply shocks before they appear in official data.",
            keywords=_CPI_KEYWORDS,
            materiality="medium",
        ),
        SourceRecommendation(
            id="prediction_market_cpi_contract",
            label="Prediction market or CPI fixing",
            source_type="market",
            source="<cpi-market-or-fixing-source>",
            role="market_prior",
            priority="high",
            rationale="Market-implied probabilities can provide a disciplined outside view when a liquid CPI contract exists.",
            requires_user_source=True,
        ),
    ]


def _macro_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    query = _gdelt_query(keywords or ["inflation", "interest rates", "growth"])
    return [
        _adapter(
            qid,
            id="gdelt_macro_watch",
            label="GDELT macro news search",
            source_type="gdelt",
            source=query,
            role="news_early_warning",
            priority="medium",
            rationale="Macro forecasts benefit from broad textual monitoring for shocks, policy changes, and consensus revisions.",
            keywords=keywords,
            materiality="medium",
        ),
        SourceRecommendation(
            id="macro_market_prior",
            label="Relevant prediction market",
            source_type="market",
            source="<market-url-or-symbol>",
            role="market_prior",
            priority="high",
            rationale="A liquid market or fixing can anchor the outside view when available.",
            requires_user_source=True,
        ),
    ]


def _health_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    query = _search_query(keywords, fallback=question.title)
    return [
        _adapter(qid, id="pubmed_literature", label="PubMed literature", source_type="pubmed", source=query, role="scientific_evidence", priority="high", rationale="Medical and public-health forecasts need primary literature and study updates.", keywords=keywords),
        _adapter(qid, id="clinical_trials", label="ClinicalTrials.gov", source_type="clinicaltrials", source=query, role="trial_status", priority="high", rationale="Trial status and results can move biomedical forecasts before headline summaries.", keywords=keywords),
        _adapter(qid, id="gdelt_health_news", label="GDELT health news search", source_type="gdelt", source=_gdelt_query(keywords), role="news_early_warning", priority="medium", rationale="News monitoring can surface outbreaks, policy changes, and hospital-system signals.", keywords=keywords),
    ]


def _technology_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    query = _search_query(keywords, fallback=question.title)
    return [
        _adapter(qid, id="arxiv_research", label="arXiv research", source_type="arxiv", source=query, role="research_frontier", priority="medium", rationale="Technology forecasts often move on papers, benchmarks, and technical releases.", keywords=keywords),
        _adapter(qid, id="hackernews_attention", label="Hacker News search", source_type="hackernews", source=query, role="community_attention", priority="low", rationale="Technical community attention can provide weak but timely release and adoption signals.", keywords=keywords),
        SourceRecommendation(id="github_repository", label="Relevant GitHub repository", source_type="githubrepo", source="<owner/repo>", role="implementation_signal", priority="medium", rationale="Repository activity is useful when the forecast depends on a specific project shipping.", requires_user_source=True),
    ]


def _regulatory_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    query = _search_query(keywords, fallback=question.title)
    return [
        _adapter(qid, id="federal_register", label="Federal Register", source_type="federalregister", source=query, role="regulatory_record", priority="high", rationale="Regulatory forecasts need primary notices, proposed rules, and final rules.", keywords=keywords),
        _adapter(qid, id="courtlistener", label="CourtListener", source_type="courtlistener", source=query, role="legal_record", priority="medium", rationale="Court dockets and opinions can move legal and regulatory outcomes.", keywords=keywords),
        _adapter(qid, id="gdelt_policy_news", label="GDELT policy news search", source_type="gdelt", source=_gdelt_query(keywords), role="news_early_warning", priority="medium", rationale="Policy news can surface committee actions, agency statements, or stakeholder shifts.", keywords=keywords),
    ]


def _disaster_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    query = _search_query(keywords, fallback=question.title)
    return [
        _adapter(qid, id="nws_alerts", label="NWS alerts", source_type="nws", source=query, role="official_warning", priority="high", rationale="Weather and disaster forecasts should watch official hazard alerts where relevant.", keywords=keywords),
        _adapter(qid, id="reliefweb_reports", label="ReliefWeb reports", source_type="reliefweb", source=query, role="humanitarian_context", priority="medium", rationale="ReliefWeb helps track disaster impacts and operational updates.", keywords=keywords),
        _adapter(qid, id="gdelt_disaster_news", label="GDELT disaster news search", source_type="gdelt", source=_gdelt_query(keywords), role="news_early_warning", priority="medium", rationale="News search adds breadth for local disruption and impact reports.", keywords=keywords),
    ]


def _company_market_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    query = _search_query(keywords, fallback=question.title)
    return [
        SourceRecommendation(id="sec_company_filings", label="SEC company filings", source_type="sec", source="<cik-or-company-url>", role="primary_company_record", priority="high", rationale="Company and market forecasts should use filings when the issuer is public.", requires_user_source=True),
        _adapter(qid, id="gdelt_company_news", label="GDELT company news search", source_type="gdelt", source=_gdelt_query(keywords), role="news_early_warning", priority="medium", rationale="Company news can surface lawsuits, product events, regulatory actions, or financing stress.", keywords=keywords),
        _rss(qid, id="company_rss_feed", label="Company or regulator RSS feed", feed_url="<feed-url>", role="textual_context", priority="medium", rationale="A domain-specific RSS feed is cleaner than a generic financial-news firehose when available.", keywords=keywords, requires_user_source=True),
    ]


def _generic_recommendations(question: ForecastQuestion, keywords: list[str]) -> list[SourceRecommendation]:
    qid = question.id
    recommendations = [
        _adapter(
            qid,
            id="gdelt_question_news",
            label="GDELT question news search",
            source_type="gdelt",
            source=_gdelt_query(keywords),
            role="news_early_warning",
            priority="medium",
            rationale="A broad textual search adds early-warning coverage for material developments related to the question.",
            keywords=keywords,
            materiality="medium",
        ),
        _rss(
            qid,
            id="domain_rss_feed",
            label="Domain-specific RSS/Atom feed",
            feed_url="<feed-url>",
            role="textual_context",
            priority="medium",
            rationale="A focused RSS/Atom feed can turn recurring news sources into filtered evidence candidates.",
            keywords=keywords,
            requires_user_source=True,
        ),
    ]
    if question.resolution_source and question.resolution_source.startswith(("http://", "https://")):
        recommendations.insert(
            0,
            SourceRecommendation(
                id="resolution_source_url",
                label="Resolution source URL",
                source_type="url",
                source=question.resolution_source,
                role="resolution_monitor",
                priority="very_high",
                rationale="The stated resolution source should be watched for official outcome or criteria updates.",
                watch_source=question.resolution_source,
                watch_command=f"forecast watch add --question {qid} --source-type url {_shell_quote(question.resolution_source)}",
            ),
        )
    elif question.resolution_source:
        recommendations.insert(
            0,
            SourceRecommendation(
                id="resolution_source_file",
                label="Resolution source file",
                source_type="file",
                source=question.resolution_source,
                role="resolution_monitor",
                priority="very_high",
                rationale="The stated local resolution source should be watched for official outcome or criteria updates.",
                watch_source=question.resolution_source,
                watch_command=f"forecast watch add --question {qid} --source-type file {_shell_quote(question.resolution_source)}",
            ),
        )
    return recommendations


def _adapter(
    question_id: str,
    *,
    id: str,
    label: str,
    source_type: str,
    source: str,
    role: str,
    priority: str,
    rationale: str,
    keywords: list[str] | None = None,
    materiality: str = "medium",
) -> SourceRecommendation:
    watch_source = f"{source_type}:{source}" if not source.startswith(f"{source_type}:") else source
    import_source = source.split(":", 1)[1] if source.startswith(f"{source_type}:") else source
    return SourceRecommendation(
        id=id,
        label=label,
        source_type=source_type,
        source=source,
        role=role,
        priority=priority,
        rationale=rationale,
        watch_source=watch_source,
        import_command=f"forecast import {source_type} {_shell_quote(import_source)} --question {question_id}",
        watch_command=f"forecast watch add --question {question_id} --source-type {source_type} {_shell_quote(watch_source)}",
        keywords=list(keywords or []),
        materiality=materiality,
    )


def _rss(
    question_id: str,
    *,
    id: str,
    label: str,
    feed_url: str,
    role: str,
    priority: str,
    rationale: str,
    keywords: list[str],
    materiality: str = "medium",
    requires_user_source: bool = False,
) -> SourceRecommendation:
    watch_source = feed_url if feed_url.startswith(("rss:", "atom:")) else f"rss:{feed_url}"
    filter_args = "".join(f" --keyword {_shell_quote(term)}" for term in keywords[:10])
    concrete_feed = feed_url.split(":", 1)[1] if feed_url.startswith(("rss:", "atom:")) else feed_url
    import_command = None if requires_user_source else (
        f"forecast import news {_shell_quote(concrete_feed)} --question {question_id}{filter_args}"
    )
    watch_command = None if requires_user_source else (
        f"forecast watch add --question {question_id} --source-type rss {_shell_quote(watch_source)}{filter_args} "
        f"--materiality {materiality}"
    )
    return SourceRecommendation(
        id=id,
        label=label,
        source_type="rss",
        source=watch_source,
        role=role,
        priority=priority,
        rationale=rationale,
        watch_source=None if requires_user_source else watch_source,
        import_command=import_command,
        watch_command=watch_command,
        keywords=list(keywords),
        materiality=materiality,
        requires_user_source=requires_user_source,
    )


def _question_text(question: ForecastQuestion) -> str:
    parts = [
        question.title,
        question.description,
        question.resolution_criteria,
        question.resolution_source or "",
        question.domain or "",
        " ".join(question.topics or []),
        " ".join(question.tags or []),
    ]
    return " ".join(part for part in parts if part).lower()


def _keywords_for_question(question: ForecastQuestion) -> list[str]:
    text = _question_text(question)
    keywords: list[str] = []
    for phrase in ("consumer price", "interest rate", "federal reserve", "public health", "clinical trial"):
        if phrase in text:
            keywords.append(phrase)
    for topic in [question.domain or "", *(question.topics or []), *(question.tags or [])]:
        cleaned = topic.strip()
        if cleaned:
            keywords.append(cleaned)
    for token in re.findall(r"[a-z][a-z0-9-]{2,}", text):
        if token in _STOPWORDS or token in keywords:
            continue
        keywords.append(token)
        if len(keywords) >= 10:
            break
    return _dedupe_terms(keywords)[:10]


def _gdelt_query(keywords: list[str]) -> str:
    terms = _dedupe_terms(keywords)[:8] or ["forecast"]
    if len(terms) == 1:
        return terms[0]
    return " OR ".join(_shell_quote(term) if " " in term else term for term in terms)


def _search_query(keywords: list[str], *, fallback: str) -> str:
    terms = _dedupe_terms(keywords)[:8]
    return " ".join(terms) if terms else fallback


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for term in terms:
        cleaned = str(term).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _dedupe_recommendations(recommendations: list[SourceRecommendation]) -> list[SourceRecommendation]:
    seen: set[tuple[str, str]] = set()
    output: list[SourceRecommendation] = []
    for recommendation in recommendations:
        key = (recommendation.source_type, recommendation.source.lower())
        if key in seen:
            continue
        seen.add(key)
        output.append(recommendation)
    return output


def _looks_like_cpi_or_inflation(text: str) -> bool:
    return text.startswith("cpi") or any(
        term in text for term in (" cpi", "consumer price", "inflation", "gasoline", "shelter rent")
    )


def _looks_like_macro(text: str) -> bool:
    return any(term in text for term in ("macro", "fed", "federal reserve", "interest rate", "unemployment", "recession", "gdp", "inflation"))


def _looks_like_health(text: str) -> bool:
    return any(term in text for term in ("health", "disease", "clinical", "trial", "drug", "vaccine", "outbreak", "hospital"))


def _looks_like_technology(text: str) -> bool:
    if re.search(r"\b(ai|llm|pypi|npm)\b", text):
        return True
    return any(
        term in text
        for term in (
            "software",
            "github",
            "open source",
            "language model",
            "model release",
            "technical benchmark",
            "package release",
        )
    )


def _looks_like_regulatory_or_legal(text: str) -> bool:
    return any(term in text for term in ("bill", "law", "court", "lawsuit", "regulation", "regulatory", "agency", "committee"))


def _looks_like_disaster_or_weather(text: str) -> bool:
    return any(term in text for term in ("weather", "storm", "hurricane", "earthquake", "wildfire", "flood", "disaster"))


def _looks_like_company_or_market(text: str) -> bool:
    return any(term in text for term in ("company", "stock", "earnings", "default", "bankruptcy", "revenue", "sec", "shares"))


def _shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+=,@%-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
