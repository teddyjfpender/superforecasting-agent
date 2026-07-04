"""Market-data providers, ported one-to-one from ``ui-tui/src/lib/marketFetch.ts``."""

from forecasting.marketdata.providers.bea import BeaProvider, parse_bea
from forecasting.marketdata.providers.bls import BlsProvider, parse_bls
from forecasting.marketdata.providers.coingecko import (
    CoingeckoProvider,
    parse_coingecko,
)
from forecasting.marketdata.providers.frankfurter import (
    FrankfurterProvider,
    parse_frankfurter,
)
from forecasting.marketdata.providers.fred import (
    FredProvider,
    parse_fred,
    parse_fred_csv,
)
from forecasting.marketdata.providers.stooq import StooqProvider, parse_stooq
from forecasting.marketdata.providers.yahoo import (
    SearchResult,
    YahooProvider,
    parse_yahoo,
    parse_yahoo_search,
    yahoo_type_to_category,
)

__all__ = [
    "FrankfurterProvider",
    "parse_frankfurter",
    "BeaProvider",
    "parse_bea",
    "CoingeckoProvider",
    "parse_coingecko",
    "FredProvider",
    "parse_fred",
    "parse_fred_csv",
    "BlsProvider",
    "parse_bls",
    "StooqProvider",
    "parse_stooq",
    "YahooProvider",
    "SearchResult",
    "parse_yahoo",
    "parse_yahoo_search",
    "yahoo_type_to_category",
]
