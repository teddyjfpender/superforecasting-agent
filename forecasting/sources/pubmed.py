"""Load and parse PubMed biomedical research evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import re
from urllib.parse import quote, urlencode, urlparse
from xml.etree import ElementTree

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .research_records import PubMedArticle
from .feeds import _local_name
from .dates import _fred_date, _fred_date_to_iso
from .values import _collapse_ws, _optional_str

def load_pubmed_articles(
    query: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    _read_json_endpoint: Callable[[str, str], object],
    _read_text_endpoint: Callable[[str, str], str],
) -> list[PubMedArticle]:
    """Load PubMed articles as timestamped biomedical evidence."""

    normalized_query = _pubmed_normalize_source(query)
    if not normalized_query:
        raise ValidationError("pubmed import query, PMID, or URL is required")
    if limit <= 0:
        raise ValidationError("pubmed import --limit must be positive")
    since_date = _fred_date(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(_fred_date_to_iso(since_date)) if since_date is not None else None

    search_endpoint = _pubmed_search_endpoint(
        normalized_query,
        limit=limit,
        since_date=since_date,
        api_base_url=api_base_url,
    )
    search_payload = _read_json_endpoint(search_endpoint, "pubmed search")
    pmids = _pubmed_search_pmids(search_payload)
    if not pmids:
        return []

    fetch_endpoint = _pubmed_fetch_endpoint(pmids[: min(limit, 100)], api_base_url=api_base_url)
    text = _read_text_endpoint(fetch_endpoint, "pubmed articles")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValidationError("pubmed articles response is not valid XML") from exc

    articles: list[PubMedArticle] = []
    for row in _pubmed_descendants(root, "PubmedArticle"):
        article = _pubmed_first_descendant(row, "Article")
        medline = _pubmed_first_descendant(row, "MedlineCitation")
        pubmed_data = _pubmed_first_descendant(row, "PubmedData")
        pmid = _pubmed_text(_pubmed_first_descendant(row, "PMID"))
        if article is None or not pmid:
            continue
        title = _pubmed_text(_pubmed_first_descendant(article, "ArticleTitle")) or f"PubMed article {pmid}"
        abstract = _pubmed_abstract(article)
        journal = _pubmed_journal(article)
        published_at = _pubmed_published_at(article)
        revised_at = _pubmed_date_to_iso(
            _pubmed_first_descendant(medline, "DateRevised") if medline is not None else None
        )
        candidate_dt = timestamp_to_datetime(published_at or revised_at)
        if since_dt is not None and (candidate_dt is None or candidate_dt < since_dt):
            continue
        doi = _pubmed_doi(pubmed_data)
        articles.append(
            PubMedArticle(
                pmid=pmid,
                title=title,
                abstract=abstract,
                journal=journal,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{quote(pmid, safe='')}/",
                doi=doi,
                published_at=published_at,
                revised_at=revised_at,
                authors=_pubmed_authors(article),
                publication_types=_pubmed_publication_types(article),
                source_name="PubMed",
                entry_id=pmid,
                raw={
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "doi": doi,
                    "published_at": published_at,
                    "revised_at": revised_at,
                    "query": normalized_query,
                },
            )
        )
        if len(articles) >= limit:
            break
    return articles


def _pubmed_normalize_source(source: str) -> str:
    raw = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source.strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc.endswith("pubmed.ncbi.nlm.nih.gov"):
        for part in parsed.path.split("/"):
            if part.isdigit():
                return part
    return raw


def _pubmed_search_endpoint(query: str, *, limit: int, since_date, api_base_url: str) -> str:
    params: dict[str, object] = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": min(limit, 100),
        "sort": "pub date",
    }
    if since_date is not None:
        params["mindate"] = f"{since_date.year:04d}/{since_date.month:02d}/{since_date.day:02d}"
        params["datetype"] = "pdat"
    endpoint_base = api_base_url.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _pubmed_fetch_endpoint(pmids: list[str], *, api_base_url: str) -> str:
    endpoint_base = _pubmed_fetch_base_url(api_base_url).rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _pubmed_fetch_base_url(api_base_url: str) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("pubmed import --api-base-url cannot be empty")
    if "efetch.fcgi" in base:
        return base
    if "esearch.fcgi" in base:
        return base.replace("esearch.fcgi", "efetch.fcgi")
    return f"{base.rstrip('/')}/efetch.fcgi"


def _pubmed_search_pmids(payload: object) -> list[str]:
    if isinstance(payload, dict):
        result = payload.get("esearchresult")
        if isinstance(result, dict):
            raw_ids = result.get("idlist") or result.get("ids")
        else:
            raw_ids = payload.get("idlist") or payload.get("ids")
    else:
        raw_ids = None
    if not isinstance(raw_ids, list):
        raise ValidationError("pubmed search response must include an idlist array")
    return [str(item).strip() for item in raw_ids if str(item).strip()]


def _pubmed_descendants(parent: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    return [child for child in parent.iter() if _local_name(child.tag) == tag]


def _pubmed_first_descendant(parent: ElementTree.Element | None, tag: str) -> ElementTree.Element | None:
    if parent is None:
        return None
    for child in parent.iter():
        if _local_name(child.tag) == tag:
            return child
    return None


def _pubmed_text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    return _collapse_ws("".join(element.itertext()))


def _pubmed_published_at(article: ElementTree.Element) -> str | None:
    article_date = _pubmed_first_descendant(article, "ArticleDate")
    if article_date is not None:
        parsed = _pubmed_date_to_iso(article_date)
        if parsed:
            return parsed
    journal_issue = _pubmed_first_descendant(article, "JournalIssue")
    if journal_issue is not None:
        pub_date = _pubmed_first_descendant(journal_issue, "PubDate")
        parsed = _pubmed_date_to_iso(pub_date)
        if parsed:
            return parsed
    return None


def _pubmed_date_to_iso(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    year_text = _pubmed_text(_pubmed_first_descendant(element, "Year"))
    if not year_text:
        medline_date = _pubmed_text(_pubmed_first_descendant(element, "MedlineDate"))
        if medline_date:
            match = re.search(r"\b(\d{4})\b", medline_date)
            year_text = match.group(1) if match else None
    if not year_text:
        return None
    try:
        year = int(year_text[:4])
    except ValueError:
        return None
    try:
        month = _pubmed_month_number(_pubmed_text(_pubmed_first_descendant(element, "Month")))
        day = _pubmed_day_number(_pubmed_text(_pubmed_first_descendant(element, "Day")))
        return datetime(year, month, day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _pubmed_month_number(value: str | None) -> int:
    if not value:
        return 1
    raw = value.strip()
    if raw.isdigit():
        month = int(raw)
        return month if 1 <= month <= 12 else 1
    month_names = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    return month_names.get(raw[:3].lower(), 1)


def _pubmed_day_number(value: str | None) -> int:
    if not value:
        return 1
    try:
        day = int(value.strip())
    except ValueError:
        return 1
    return day if 1 <= day <= 31 else 1


def _pubmed_abstract(article: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in _pubmed_descendants(article, "AbstractText"):
        text = _pubmed_text(node)
        if not text:
            continue
        label = _optional_str(node.attrib.get("Label"))
        parts.append(f"{label}: {text}" if label else text)
    return _collapse_ws(" ".join(parts))


def _pubmed_journal(article: ElementTree.Element) -> str | None:
    journal = _pubmed_first_descendant(article, "Journal")
    if journal is None:
        return None
    return _pubmed_text(_pubmed_first_descendant(journal, "Title")) or _pubmed_text(
        _pubmed_first_descendant(journal, "ISOAbbreviation")
    )


def _pubmed_authors(article: ElementTree.Element) -> list[str]:
    authors = []
    for author in _pubmed_descendants(article, "Author"):
        collective = _pubmed_text(_pubmed_first_descendant(author, "CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = _pubmed_text(_pubmed_first_descendant(author, "LastName"))
        fore = _pubmed_text(_pubmed_first_descendant(author, "ForeName"))
        initials = _pubmed_text(_pubmed_first_descendant(author, "Initials"))
        name = " ".join(part for part in (fore or initials, last) if part)
        if name:
            authors.append(name)
    return authors


def _pubmed_publication_types(article: ElementTree.Element) -> list[str]:
    return [
        text
        for node in _pubmed_descendants(article, "PublicationType")
        for text in [_pubmed_text(node)]
        if text
    ]


def _pubmed_doi(pubmed_data: ElementTree.Element | None) -> str | None:
    if pubmed_data is None:
        return None
    for article_id in _pubmed_descendants(pubmed_data, "ArticleId"):
        if article_id.attrib.get("IdType", "").lower() == "doi":
            return _pubmed_text(article_id)
    return None
