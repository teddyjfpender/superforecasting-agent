"""Live-directory contracts, honest failure isolation and ranked intent matching."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from forecasting.marketdata.catalog import load_catalog
from forecasting.marketdata.discovery import Discovery, catalog_hits
from forecasting.marketdata.discovery_worldbank import directory, search_directory
from forecasting.marketdata.model import Quote
from forecasting.marketdata.provider import ProviderFailure
from forecasting.marketdata.providers.yahoo import YahooProvider
from protocol.rpc.markets import MarketDiscoverRequest


def test_catalog_country_intent_and_exact_identifier():
    catalog = load_catalog()
    hits = catalog_hits(catalog, MarketDiscoverRequest(query='Brazil jobs'))
    assert hits and all(h.country == 'BRA' and h.category == 'employment' for h in hits)
    hits = catalog_hits(catalog, MarketDiscoverRequest(query='SOFR'))
    assert hits[0].symbol == 'SOFR'
    country_hits = catalog_hits(catalog, MarketDiscoverRequest(query='US jobs'))
    assert country_hits and all(h.country == 'USA' for h in country_hits)
    assert catalog_hits(catalog, MarketDiscoverRequest(query='Germany nonexistent unicorn')) == []
    assert all(h.region in {'europe','middle-east','africa'} for h in catalog_hits(catalog, MarketDiscoverRequest(query='', region='emea')))


def test_live_search_is_independent_of_subscriptions_and_deduplicates_catalog():
    source = YahooProvider(get_json=lambda url: {'quotes':[
        {'symbol':'AAPL','shortname':'Apple','quoteType':'EQUITY'},
        {'symbol':'NEW','shortname':'New listing','quoteType':'EQUITY'}]})
    service = Discovery({'yahoo': source}, lambda p: None)
    result = service.discover(MarketDiscoverRequest(query='AAPL'), load_catalog())
    assert len([h for h in result.results if h.symbol == 'AAPL']) == 1
    assert next(h for h in result.results if h.symbol == 'AAPL').catalog_id == 'yahoo:AAPL'
    hit = next(h for h in result.results if h.symbol == 'NEW')
    assert hit.catalog_id is None and hit.id == 'custom:yahoo:NEW'


def test_failed_source_does_not_hide_good_hits_or_leak_credentials():
    def fetch(url):
        if 'coingecko' in url:
            raise RuntimeError('private-token=secret')
        return {'seriess':[{'id':'NEWCPI','title':'Consumer prices','units':'Index','frequency':'Monthly'}]}
    service = Discovery({'fred': object(), 'coingecko': object()}, lambda p: 'test-key', get_json=fetch)
    result = service.discover(MarketDiscoverRequest(query='prices'), load_catalog())
    assert any(h.symbol == 'NEWCPI' and h.unit == 'Index' for h in result.results)
    assert next(s for s in result.statuses if s.provider == 'coingecko').status == 'unavailable'
    assert 'secret' not in result.model_dump_json()


def test_fred_keyword_credentials_and_keyless_exact_id():
    class Source:
        def fetch(self, series):
            return [Quote(provider='fred',symbol=series[0].symbol,name='',category='',value=1,change=None,changePct=None,prevClose=None,asOf=0,unit='')]
    service = Discovery({'fred': Source()}, lambda p: None)
    result = service.discover(MarketDiscoverRequest(query='interest rate', provider='fred'), load_catalog())
    assert result.statuses[0].status == 'credentials_required'
    hit = service.discover(MarketDiscoverRequest(query='OUTSIDE123',provider='fred'),load_catalog()).results[0]
    assert hit.symbol == 'OUTSIDE123' and hit.unit == '' and hit.catalog_id is None


def test_success_cache_is_bounded_and_source_busy_does_not_queue():
    started, release = Event(), Event()
    service = Discovery({'yahoo': YahooProvider()}, lambda p: None)
    def live(provider, query):
        started.set()
        release.wait(3)
        return []
    service._live = live
    for _ in range(4):
        service._slots.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(service._search, 'yahoo', 'A')
        assert started.wait(1)
        assert service._search('yahoo', 'B')[1].status == 'busy'
        release.set()
        assert task.result()[1].status == 'ok'
    assert service._search('yahoo','A')[1].status == 'cached'
    for _ in range(4):
        service._slots.release()
    service._live = lambda p, q: []
    for i in range(140): service._search('yahoo', str(i))
    assert len(service._cache) == 128


COUNTRIES = [{'id':'ZMB','name':'Zambia','region':{'id':'SSF'}}, {'id':'WLD','name':'World','region':{'id':'NA'}}]
INDICATORS = [
    {'id':'SP.POP.TOTL','name':'Population, total','unit':'','sourceNote':'Total residents'},
    {'id':'EG.ELC.ACCS.ZS','name':'Access to electricity (% of population)','unit':''},
    {'id':'IT.NET.USER.ZS','name':'Individuals using the Internet (% of population)','unit':'%'}]


def test_worldbank_discovers_outside_preset_and_preserves_unknown_units():
    hits = search_directory('Zambia population', COUNTRIES, INDICATORS)
    assert hits[0].symbol == 'ZMB/SP.POP.TOTL'
    assert hits[0].unit == '' and hits[0].catalog_id is None
    assert search_directory('ZMB Zambia population', COUNTRIES, INDICATORS)[0].symbol == 'ZMB/SP.POP.TOTL'
    assert search_directory('ZMB/IT.NET.USER.ZS', COUNTRIES, INDICATORS)[0].symbol == 'ZMB/IT.NET.USER.ZS'
    assert search_directory('World population', COUNTRIES, INDICATORS) == []
    assert search_directory('Zambia invented thing', COUNTRIES, INDICATORS) == []
    with pytest.raises(ProviderFailure, match='page budget'):
        directory([{'pages':2}, INDICATORS])


def test_worldbank_directory_cached_and_country_filter_applied():
    calls=[]
    def fetch(url):
        calls.append(url)
        return [{'pages':1}, COUNTRIES if '/country?' in url else INDICATORS]
    service=Discovery({'worldbank':object()},lambda p: None,get_json=fetch)
    result=service.discover(MarketDiscoverRequest(query='internet',country='ZMB',provider='worldbank'),load_catalog())
    assert result.results[0].symbol=='ZMB/IT.NET.USER.ZS'
    service.discover(MarketDiscoverRequest(query='Zambia population',provider='worldbank'),load_catalog())
    assert len(calls)==2

