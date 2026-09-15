"""Small, reviewed global news collection; availability is qualified separately."""

from protocol.rpc.news import NewsSubscription

# Public publisher endpoints, not scraped mirrors or synthetic headlines.
_ROWS = (
    (
        "Markets",
        "CNBC · Markets",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ),
    ("Business", "BBC · Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("World", "BBC · World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("World", "Al Jazeera · World", "https://www.aljazeera.com/xml/rss/all.xml"),
    (
        "Europe",
        "Guardian · Europe",
        "https://www.theguardian.com/world/europe-news/rss",
    ),
    (
        "Asia Pacific",
        "CNA · Asia",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511",
    ),
    (
        "Asia Pacific",
        "CNA · Business",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936",
    ),
    (
        "Latin America",
        "MercoPress · Latin America",
        "https://en.mercopress.com/rss/latin-america",
    ),
    (
        "Middle East",
        "Guardian · Middle East",
        "https://www.theguardian.com/world/middleeast/rss",
    ),
    ("Africa", "Guardian · Africa", "https://www.theguardian.com/world/africa/rss"),
    (
        "Central Banks",
        "Federal Reserve · Policy",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
    ),
    (
        "Central Banks",
        "ECB · Press and speeches",
        "https://www.ecb.europa.eu/rss/press.html",
    ),
    ("Economics", "BLS · Economic releases", "https://www.bls.gov/feed/bls_latest.rss"),
    ("Energy", "EIA · Today in Energy", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("Technology", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("Science", "NASA · News", "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
    ("Climate", "Carbon Brief", "https://www.carbonbrief.org/feed/"),
    ("Weather", "NHC · Atlantic storms", "https://www.nhc.noaa.gov/index-at.xml"),
    ("Disasters", "GDACS · Global alerts", "https://www.gdacs.org/xml/rss.xml"),
)


def starter_feeds() -> list[NewsSubscription]:
    return [
        NewsSubscription(category=category, title=title, url=url)
        for category, title, url in _ROWS
    ]
