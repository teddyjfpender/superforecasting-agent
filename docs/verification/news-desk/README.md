# Global news desk qualification

The [live feed audit](2026-09-15-feeds.json) retrieved entries from all 19 starter
sources on 15 September 2026. This checks availability, not perpetual service or
editorial reliability. Sources retain their own publication times and attribution.
The [article audit](2026-09-15-articles.json) recovered article text on all six
sampled pages, including legacy Federal Reserve, EIA and MercoPress layouts.
Unavailable or access-gated pages still fall back to labeled excerpts.

Setup offers **Global news starter** or **Start empty**. Existing subscriptions
are preserved. In News, **s** previews the starter and **Enter** applies it;
repeating this adds only missing feeds. **a** manages individual subscriptions.

The reader retains longer RSS/Atom content and fetches accessible article text
after selection settles. **PgUp/PgDn** scrolls; **Enter** opens the original source.
Source excerpts and unavailable bodies are labeled. Refresh failures keep the
previous headlines visible. Exact link duplicates collapse; independent reporting
remains separate. No LLM rewrites or synthetic news fill the desk.

This is a public-feed desk, not a Bloomberg subscription or paid wire entitlement.
Publisher terms apply, including CNA's personal, non-commercial RSS restriction:
[CNA feeds and terms](https://www.channelnewsasia.com/rss),
[ECB feed directory](https://www.ecb.europa.eu/home/html/rss.en.html),
[MercoPress feed directory](https://en.mercopress.com/feeds).

Subscriptions and requests use the connected backend profile, including on a VPS.
The legacy `news_feeds.json` array/object formats remain readable; malformed
files fail closed. Remote clients do not silently substitute their local news
profile. Feed caches are view-local for backend connections; revisiting News
refreshes sources. Article extraction is best effort; dynamic and gated pages may
still supply only a teaser. Windows/Linux network availability was not requalified
by this macOS source audit.
