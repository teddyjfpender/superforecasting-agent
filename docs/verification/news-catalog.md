# News catalog qualification — 2026-09-16

Added 32 publisher/institution feeds to the 519-entry discovery catalog:
**551 feeds across 54 categories**. This is an opt-in catalog expansion;
existing subscriptions and the smaller setup starter are unchanged.

## Method and limits

Each addition returned RSS/Atom through the production Python news transport
(verified TLS, public URL checks, redirect checks, 2 MiB cap and timeouts).
Its response was passed through the TUI's actual `parseFeed`; every feed produced
articles with nonempty titles, HTTP(S) links and parseable publication dates.
The table records the observed counts and first entry's source date. These are
point-in-time observations, not uptime promises or a requalification of the
519 inherited feeds. No article bodies are committed or redistributed.

Official discovery references include [Le Monde's directory](https://www.lemonde.fr/en/about-us/article/2026/03/27/le-monde-rss-feeds_6751860_115.html),
[BIS](https://www.bis.org/rss), [ECB](https://www.ecb.europa.eu/home/html/rss.en.html),
[FTC](https://www.ftc.gov/stay-connected/rss) and
[WTO](https://www.wto.org/english/res_e/webcas_e/rss_e.htm).
Other rows link directly to the publisher-owned feed that was fetched.

Public feeds supplement a forecasting desk with reporting, analysis and primary
announcements. They do not replace a licensed terminal wire or guarantee
real-time delivery. Publisher restrictions still apply; the reader never
bypasses paywalls. Subscription-dependent sources are labeled in catalog copy.

## Verified additions

| Source | Category | Parsed / dated and linked | First entry source date |
| --- | --- | ---: | --- |
| [Financial Times · Markets](https://www.ft.com/markets?format=rss) | Markets | 25 / 25 | Wed, 16 Sep 2026 05:00:02 GMT |
| [Financial Times · Global economy](https://www.ft.com/global-economy?format=rss) | Economics | 25 / 25 | Wed, 16 Sep 2026 04:30:53 GMT |
| [Le Monde · In English](https://www.lemonde.fr/en/rss/une.xml) | Europe | 18 / 18 | Wed, 16 Sep 2026 04:30:08 +0200 |
| [Le Monde · M magazine](https://www.lemonde.fr/en/m-le-mag/rss_full.xml) | Magazines | 20 / 20 | Mon, 14 Sep 2026 05:30:07 +0200 |
| [Foreign Policy](https://foreignpolicy.com/feed/) | Geopolitics | 25 / 25 | Tue, 15 Sep 2026 21:35:37 +0000 |
| [The Diplomat](https://thediplomat.com/feed/) | Geopolitics | 96 / 96 | Tue, 15 Sep 2026 22:39:00 +0900 |
| [Harper’s Magazine](https://harpers.org/feed/) | Magazines | 10 / 10 | Tue, 15 Sep 2026 15:00:49 +0000 |
| [New York Times · World](https://rss.nytimes.com/services/xml/rss/nyt/World.xml) | World | 57 / 57 | Tue, 15 Sep 2026 09:13:29 +0000 |
| [New York Times · Business](https://rss.nytimes.com/services/xml/rss/nyt/Business.xml) | Business | 50 / 50 | Wed, 16 Sep 2026 04:01:30 +0000 |
| [Deutsche Welle · World](https://rss.dw.com/rdf/rss-en-world) | Europe | 12 / 12 | 2026-09-15T19:32:00Z |
| [France 24 · English](https://www.france24.com/en/rss) | Europe | 24 / 24 | Wed, 16 Sep 2026 05:20:56 GMT |
| [The Hindu · Business](https://www.thehindu.com/business/feeder/default.rss) | Asia Pacific | 60 / 60 | Wed, 16 Sep 2026 10:23:58 +0530 |
| [South China Morning Post · Asia](https://www.scmp.com/rss/4/feed) | Asia Pacific | 50 / 50 | Wed, 16 Sep 2026 04:00:09 +0000 |
| [ABC Australia · Business](https://www.abc.net.au/news/feed/51892/rss.xml) | Asia Pacific | 25 / 25 | Wed, 16 Sep 2026 03:33:02 +0000 |
| [African Business](https://african.business/feed) | Africa | 25 / 25 | Tue, 15 Sep 2026 15:01:29 +0000 |
| [Daily Maverick](https://www.dailymaverick.co.za/dmrss/) | Africa | 52 / 52 | Wed, 16 Sep 2026 07:00:00 GMT |
| [Al-Monitor](https://www.al-monitor.com/rss) | Middle East | 20 / 20 | 2026-09-15T23:30:29-0400 |
| [MercoPress · Economy](https://en.mercopress.com/rss/economy) | Latin America | 10 / 10 | Tue, 15 Sep 2026 18:46:00 GMT |
| [BIS · Central bankers’ speeches](https://www.bis.org/doclist/cbspeeches.rss) | Central Banks | 50 / 50 | 2026-09-15T00:00:00Z |
| [BIS · Statistics](https://data.bis.org/feed.xml) | Economic Releases | 98 / 98 | Thu, 27 Aug 2026 10:00:00 GMT |
| [ECB · Statistics](https://www.ecb.europa.eu/rss/statpress.html) | Economic Releases | 15 / 15 | Wed, 02 Sep 2026 10:00:00 +0200 |
| [FTC · Press releases](https://www.ftc.gov/feeds/press-release.xml) | Regulation | 10 / 10 | Tue, 15 Sep 2026 08:00:00 -0400 |
| [EIA · Today in Energy](https://www.eia.gov/rss/todayinenergy.xml) | Energy | 16 / 16 | Tue, 15 Sep 2026  09:00:00 EST |
| [Utility Dive](https://www.utilitydive.com/feeds/news/) | Energy | 10 / 10 | Tue, 15 Sep 2026 13:00:17 -0400 |
| [Carbon Brief](https://www.carbonbrief.org/feed/) | Climate | 12 / 12 | Tue, 15 Sep 2026 23:01:00 +0000 |
| [Yale Environment 360](https://e360.yale.edu/feed.xml) | Climate | 100 / 100 | 2026-09-15T08:47:00-04:00 |
| [The Loadstar](https://theloadstar.com/feed/) | Trade & Logistics | 10 / 10 | Tue, 15 Sep 2026 12:16:09 +0000 |
| [gCaptain](https://gcaptain.com/feed/) | Trade & Logistics | 12 / 12 | Tue, 15 Sep 2026 22:55:51 +0000 |
| [STAT](https://www.statnews.com/feed/) | Health | 20 / 20 | Tue, 15 Sep 2026 18:43:59 +0000 |
| [BIS · Research](https://www.bis.org/doclist/bis_fsi_publs.rss) | Central Banks | 20 / 20 | 2026-09-15T00:00:00Z |
| [WTO · News](https://www.wto.org/library/rss/latest_news_e.xml) | Trade & Logistics | 10 / 10 | Tue, 15 Sep 2026 00:00:00 GMT |
| [SEC · Press releases](https://www.sec.gov/news/pressreleases.rss) | Regulation | 25 / 25 | Mon, 14 Sep 2026 12:47:00 -0400 |

## Candidates not admitted

- RBA media releases and MINING.COM returned HTTP 403 in this environment.
- The New York Review of Books candidate contained no RSS/Atom entries.
- Initial BEA and BIS research URLs returned 404. BIS was replaced with the
  endpoint linked by its official directory and successfully qualified above;
  BEA was not added.

A blocked candidate may work elsewhere; it needs another recorded qualification
before inclusion. No authentication bypass or mirror was used.

## Repeatable checks

- `python3 scripts/gen-news-catalog.py --check` — deterministic catalog and URL validation.
- `scripts/run_tests.sh tests/scripts/test_news_catalog.py` — stale output,
  invalid URLs and case-sensitive identity regressions.
- `npm --prefix ui-tui test -- src/__tests__/newsFeedSearch.test.ts` — metadata,
  category coverage and discovery by desk-oriented search terms.
