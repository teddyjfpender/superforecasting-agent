"""News starter persistence and article source boundaries."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from forecasting.news.articles import extract_article
from forecasting.news.catalog import starter_feeds
from protocol.rpc.news import NewsConfigureRequest, NewsSubscription
from superforecasting_agent.application.news_desk import NewsDesk


def test_starter_additive_idempotent_and_empty_durable(tmp_path):
    desk = NewsDesk(tmp_path)
    assert desk.selection().state == "unconfigured"
    desk.configure(NewsConfigureRequest(action="empty"))
    assert NewsDesk(tmp_path).selection().state == "configured"
    custom = NewsSubscription(url="https://example.org/Case?ID=1", title="Mine", category="Custom", custom=True)
    desk.configure(NewsConfigureRequest(action="add", feed=custom))
    first = desk.configure(NewsConfigureRequest(action="starter"))
    assert first.feeds[0].url == custom.url
    assert len(first.feeds) == len(starter_feeds()) + 1
    assert desk.configure(NewsConfigureRequest(action="starter")) == first
    with pytest.raises(ValueError):
        desk.configure(NewsConfigureRequest(action="empty"))


def test_legacy_and_unknown_fields_survive_concurrent_adds(tmp_path):
    path = tmp_path / "news_feeds.json"
    path.write_text(json.dumps({"feeds": [{"url": "example.org/feed", "title": "Old"}], "future": {"keep": True}}))
    def add(i):
        return NewsDesk(tmp_path).configure(NewsConfigureRequest(action="add", feed=NewsSubscription(url=f"https://example.org/{i}", title=str(i), category="News")))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(8)))
    assert len(NewsDesk(tmp_path).selection().feeds) == 9
    assert json.loads(path.read_text())["future"] == {"keep": True}
    path.write_text("broken")
    with pytest.raises(ValueError):
        NewsDesk(tmp_path).configure(NewsConfigureRequest(action="starter"))
    assert path.read_text() == "broken"


def test_case_sensitive_feed_paths_are_distinct(tmp_path):
    desk = NewsDesk(tmp_path)
    for suffix in ("Feed?ID=A", "feed?ID=a"):
        desk.configure(NewsConfigureRequest(action="add", feed=NewsSubscription(url="https://example.org/" + suffix, title=suffix, category="News")))
    assert len(desk.selection().feeds) == 2


@pytest.mark.parametrize("choice", [0, 1])
def test_setup_does_not_reseed_explicit_choices(tmp_path, monkeypatch, choice):
    from superforecasting_agent.runtime import setup
    from superforecasting_agent.runtime.news_desk import setup_news_desk
    answers = iter([choice])
    monkeypatch.setattr(setup, "prompt_choice", lambda *args: next(answers))
    monkeypatch.setattr(setup, "print_info", lambda *args: None)
    setup_news_desk(tmp_path)
    setup_news_desk(tmp_path)
    assert bool(NewsDesk(tmp_path).selection().feeds) == (choice == 0)


PARAGRAPH = "The committee published its decision and detailed the reasons for the change. " * 8


def test_article_body_excludes_controls_hidden_text_and_preserves_paragraphs():
    html = f'<main>Navigation<article>Reader settings<div class="post-content"><p>{PARAGRAPH}</p><p>Second paragraph.</p><script>secret()</script><aside>Related stories</aside><p hidden>Hidden paywall</p></div>Footer controls</article></main>'
    result = extract_article(html, "https://example.org/story")
    assert result.status == "article"
    assert "\n\nSecond paragraph." in result.text
    for excluded in ("settings", "secret", "Related", "Hidden", "Navigation", "Footer"):
        assert excluded not in result.text


@pytest.mark.parametrize("url,container", [
    ("https://www.eia.gov/story", 'class="tie-article"'),
    ("https://www.federalreserve.gov/story", 'id="article"'),
    ("https://en.mercopress.com/story", 'class="cnt"'),
])
def test_verified_legacy_body_containers(url, container):
    assert extract_article(f'<div {container}><p>{PARAGRAPH}</p></div>', url).status == "article"
    assert extract_article(f'<div {container}><p>{PARAGRAPH}</p></div>', "https://unrelated.org/").status == "unavailable"


def test_access_gate_does_not_mine_hidden_body_and_empty_is_honest():
    result = extract_article(f'<meta name="description" content="Public excerpt"><script type="application/ld+json">{{"isAccessibleForFree":false,"articleBody":"Secret"}}</script><article>{PARAGRAPH}</article>', "https://example.org/")
    assert result.status == "excerpt"
    assert result.text == "Public excerpt"
    assert extract_article('<nav>Links</nav>', 'https://example.org').status == "unavailable"


def test_gateway_contracts_and_failures(tmp_path, monkeypatch):
    from protocol.validation import contract_handler
    from tui_gateway import news_rpc
    monkeypatch.setattr(news_rpc, "get_agent_home", lambda: tmp_path)
    methods = {}
    server = SimpleNamespace(register_method=lambda name, fn: methods.update({name: contract_handler(name, fn)}), _ok=lambda rid, result: result, _err=lambda rid, code, message: {"error": message})
    news_rpc.register(server)
    assert methods['news.desk'](1, {})['state'] == 'unconfigured'
    assert len(methods['news.configure'](2, {"action": "starter"})['feeds']) == len(starter_feeds())
    monkeypatch.setattr(news_rpc, 'fetch_public_text', lambda url: (_ for _ in ()).throw(ValueError("unsafe")))
    assert methods['news.article'](3, {"url": "http://127.0.0.1"})['status'] == 'unavailable'


def test_transport_blocks_redirects_before_sending_and_caps_body(monkeypatch):
    import httpx
    from forecasting.news.transport import fetch_public_text, MAX_BYTES
    from tools import url_safety
    original_client = httpx.Client
    seen = []
    def respond(request):
        seen.append(str(request.url))
        if request.url.path == '/redirect':
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        return httpx.Response(200, stream=httpx.ByteStream(b'x' * (MAX_BYTES + 1)))
    monkeypatch.setattr(url_safety, 'is_safe_url', lambda url: '127.0.0.1' not in url)
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(ValueError, match='public HTTP'):
        fetch_public_text('https://example.org/redirect', is_safe_url=url_safety.is_safe_url)
    assert seen == ['https://example.org/redirect']
    with pytest.raises(ValueError, match='budget'):
        fetch_public_text('https://example.org/large', is_safe_url=url_safety.is_safe_url)
