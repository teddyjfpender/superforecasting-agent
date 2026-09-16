# News catalog qualification — 2026-09-16

Two review passes added 89 publisher/institution feeds to the 519-entry catalog:
**608 feeds across 59 categories** (32 in the first pass, 57 in the follow-up). This is an opt-in catalog expansion;
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

## First pass: 32 verified additions

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

## First-pass candidates not admitted

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

## Follow-up: 57 additional verified feeds

Reviewed 84 initial/replacement candidates, then corrected and qualified two
GlobeNewswire subject endpoints against its [official directory](https://rss.globenewswire.com/rss/list).
Each admitted feed passed the same production transport and TUI parser checks.
The table records parsed articles, dated/linkable articles and the newest past
publication in UTC. All admitted feeds had an article within the preceding
90 days and no future-dated articles in these samples. This is a qualification
observation, not a new runtime freshness rule or an uptime guarantee.

The new categories are **Agriculture, Commodities, Company Releases,
Cybersecurity and Defense**. Existing regions and specialist categories also
receive more depth. Corporate feeds are labeled as issuer-supplied claims;
GlobeNewswire feeds contain multiple languages. No copied article text ships
with this catalog. All additions are opt-in.

| Source | Category | Parsed / dated and linked | Newest past publication (UTC) |
| --- | --- | ---: | --- |
| [Premium Times · Business](https://www.premiumtimesng.com/category/business/feed) | Africa | 15 / 15 | 2026-09-15T16:59:33.000Z |
| [The Africa Report](https://www.theafricareport.com/feed/) | Africa | 10 / 10 | 2026-09-16T05:00:00.000Z |
| [Agriland](https://www.agriland.ie/feed/) | Agriculture | 80 / 80 | 2026-09-16T05:15:00.000Z |
| [FAO · News](https://www.fao.org/feeds/fao-newsroom-rss) | Agriculture | 17 / 17 | 2026-09-15T12:00:00.000Z |
| [Food Dive](https://www.fooddive.com/feeds/news/) | Agriculture | 10 / 10 | 2026-09-15T20:02:00.000Z |
| [CNA · Asia](https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511) | Asia Pacific | 20 / 20 | 2026-09-16T05:16:00.000Z |
| [Dawn · Business](https://www.dawn.com/feeds/business) | Asia Pacific | 30 / 30 | 2026-09-16T03:13:52.000Z |
| [Japan Times · News](https://www.japantimes.co.jp/feed/) | Asia Pacific | 30 / 30 | 2026-09-16T05:23:00.000Z |
| [The Diplomat · Economics](https://thediplomat.com/topics/economy/feed/) | Asia Pacific | 96 / 96 | 2026-09-15T14:08:00.000Z |
| [The Hindu · International](https://www.thehindu.com/news/international/feeder/default.rss) | Asia Pacific | 60 / 60 | 2026-09-16T05:28:48.000Z |
| [Electrek](https://electrek.co/feed/) | Business | 100 / 100 | 2026-09-15T21:45:23.000Z |
| [Semiconductor Engineering](https://semiengineering.com/feed/) | Business | 10 / 10 | 2026-09-15T07:13:41.000Z |
| [Bank of Canada · Releases](https://www.bankofcanada.ca/content_type/press-releases/feed/) | Central Banks | 10 / 10 | 2026-09-10T11:00:09.000Z |
| [Bank of Japan · News](https://www.boj.or.jp/en/rss/whatsnew.xml) | Central Banks | 42 / 42 | 2026-09-15T06:00:00.000Z |
| [ECB · Blog](https://www.ecb.europa.eu/rss/blog.html) | Central Banks | 15 / 15 | 2026-09-15T09:00:00.000Z |
| [Federal Reserve · Policy](https://www.federalreserve.gov/feeds/press_monetary.xml) | Central Banks | 15 / 15 | 2026-08-25T18:00:00.000Z |
| [Federal Reserve · Speeches](https://www.federalreserve.gov/feeds/speeches.xml) | Central Banks | 15 / 15 | 2026-09-03T12:30:00.000Z |
| [Inside Climate News](https://insideclimatenews.org/feed/) | Climate | 10 / 10 | 2026-09-15T23:22:50.000Z |
| [Mongabay](https://news.mongabay.com/feed/) | Climate | 32 / 32 | 2026-09-15T21:38:13.000Z |
| [Mining Technology](https://www.mining-technology.com/feed/) | Commodities | 10 / 10 | 2026-09-15T13:11:54.000Z |
| [Oilprice.com](https://oilprice.com/rss/main) | Commodities | 15 / 15 | 2026-09-16T00:00:00.000Z |
| [World Nuclear News](https://www.world-nuclear-news.org/rss) | Commodities | 51 / 51 | 2026-09-15T16:10:36.000Z |
| [Boeing · Press releases](https://boeing.mediaroom.com/news-releases-statements?pagetemplate=rss) | Company Releases | 5 / 5 | 2026-09-15T23:42:00.000Z |
| [GlobeNewswire · Earnings](https://rss.globenewswire.com/RssFeed/subjectcode/13-Earnings%20Releases%20and%20Operating%20Results/feedTitle/GlobeNewswire%20-%20Earnings%20Releases%20and%20Operating%20Results) | Company Releases | 20 / 20 | 2026-09-15T20:35:00.000Z |
| [GlobeNewswire · Mergers](https://rss.globenewswire.com/RssFeed/subjectcode/27-Mergers%20and%20Acquisitions/feedTitle/GlobeNewswire%20-%20Mergers%20and%20Acquisitions) | Company Releases | 20 / 20 | 2026-09-16T05:30:00.000Z |
| [Microsoft · Announcements](https://blogs.microsoft.com/feed/) | Company Releases | 10 / 10 | 2026-09-02T06:00:02.000Z |
| [NVIDIA · Press releases](https://nvidianews.nvidia.com/releases.xml) | Company Releases | 20 / 20 | 2026-09-16T05:00:42.000Z |
| [BleepingComputer](https://www.bleepingcomputer.com/feed/) | Cybersecurity | 15 / 15 | 2026-09-15T21:37:35.000Z |
| [CISA · Advisories](https://www.cisa.gov/cybersecurity-advisories/all.xml) | Cybersecurity | 30 / 30 | 2026-09-15T12:00:00.000Z |
| [Krebs on Security](https://krebsonsecurity.com/feed/) | Cybersecurity | 10 / 10 | 2026-09-08T21:44:22.000Z |
| [Breaking Defense](https://breakingdefense.com/feed/) | Defense | 15 / 15 | 2026-09-16T01:39:31.000Z |
| [Defense News](https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml) | Defense | 25 / 25 | 2026-09-15T20:55:49.000Z |
| [War on the Rocks](https://warontherocks.com/feed/) | Defense | 100 / 100 | 2026-09-15T18:45:59.000Z |
| [BEA · Releases](https://apps.bea.gov/rss/rss.xml) | Economic Releases | 48 / 48 | 2026-09-03T12:30:00.000Z |
| [FRED Blog](https://fredblog.stlouisfed.org/feed/) | Economics | 10 / 10 | 2026-09-14T13:00:00.000Z |
| [PV Magazine](https://www.pv-magazine.com/feed/) | Energy | 10 / 10 | 2026-09-16T05:14:39.000Z |
| [Deutsche Welle · Business](https://rss.dw.com/rdf/rss-en-bus) | Europe | 20 / 20 | 2026-09-15T13:17:00.000Z |
| [Euractiv](https://www.euractiv.com/feed/) | Europe | 100 / 100 | 2026-09-16T04:00:22.000Z |
| [POLITICO Europe](https://www.politico.eu/feed/) | Europe | 10 / 10 | 2026-09-16T05:18:30.000Z |
| [International Crisis Group](https://www.crisisgroup.org/rss.xml) | Geopolitics | 10 / 10 | 2026-09-14T15:03:11.000Z |
| [Responsible Statecraft](https://responsiblestatecraft.org/feed/) | Geopolitics | 30 / 30 | 2026-09-16T00:03:30.000Z |
| [KFF Health News](https://kffhealthnews.org/feed/) | Health | 10 / 10 | 2026-09-15T09:00:00.000Z |
| [Brazil Reports](https://brazilreports.com/feed/) | Latin America | 15 / 15 | 2026-08-28T22:16:37.000Z |
| [Buenos Aires Times](https://www.batimes.com.ar/feed) | Latin America | 100 / 100 | 2026-09-15T23:12:11.000Z |
| [Colombia Reports](https://colombiareports.com/feed/) | Latin America | 10 / 10 | 2026-09-15T13:58:35.000Z |
| [Rio Times](https://www.riotimesonline.com/feed/) | Latin America | 10 / 10 | 2026-09-15T21:22:29.000Z |
| [London Review of Books · Blog](https://www.lrb.co.uk/blog/feed) | Magazines | 5 / 5 | 2026-09-15T14:44:07.000Z |
| [ProPublica](https://www.propublica.org/feeds/propublica/main) | Magazines | 20 / 20 | 2026-09-15T21:50:00.000Z |
| [Rest of World](https://restofworld.org/feed/) | Magazines | 12 / 12 | 2026-09-15T10:00:00.000Z |
| [The New Statesman](https://www.newstatesman.com/feed) | Magazines | 20 / 20 | 2026-09-16T05:00:00.000Z |
| [Undark](https://undark.org/feed/) | Magazines | 10 / 10 | 2026-09-11T07:36:32.000Z |
| [Arab News](https://www.arabnews.com/rss.xml) | Middle East | 50 / 50 | 2026-09-16T05:37:47.000Z |
| [UK · Financial sanctions](https://www.gov.uk/government/organisations/office-of-financial-sanctions-implementation.atom) | Regulation | 20 / 20 | 2026-09-02T09:22:20.000Z |
| [SpaceNews](https://spacenews.com/feed/) | Space | 6 / 6 | 2026-09-15T15:49:31.000Z |
| [FreightWaves](https://www.freightwaves.com/feed) | Trade & Logistics | 50 / 50 | 2026-09-15T20:13:51.000Z |
| [Supply Chain Dive](https://www.supplychaindive.com/feeds/news/) | Trade & Logistics | 10 / 10 | 2026-09-15T15:41:00.000Z |
| [The Maritime Executive](https://maritime-executive.com/articles.rss) | Trade & Logistics | 69 / 69 | 2026-09-16T03:11:15.000Z |

### Findings and rejected candidates

- **Stale despite valid XML:** WHO News' newest item was 2026-02-25; the
  candidate CIDRAP feed stopped in 2022. Neither was added. Alternate outbreak
  and CIDRAP candidates returned 404.
- **Missing/ambiguous dates:** Nikkei Asia supplied no recognized publication
  dates; Fierce Biotech used a date string without a timezone that the TUI
  cannot safely parse. Neither was added; dates were not guessed.
- **Upcoming events:** Bank of Canada's broad press feed contained four future
  events. Its narrower press-releases feed passed with zero future entries and
  is the version admitted.
- **Subject identity:** GlobeNewswire's title is caller-supplied and does not
  establish the feed's topic. The directory identifies earnings as subject 13
  and mergers as 27. Initial guessed IDs were rejected after inspecting their
  contents; the two correct feeds returned actual results and deal announcements.
- **Recovered endpoints:** BEA uses `apps.bea.gov/rss/rss.xml`; Maritime Executive
  uses `articles.rss`. Both passed. The GlobeNewswire RSS host worked where
  requests to its main host timed out.
- **Not qualified here:** Statistics Canada, PR Newswire, USDA crop headlines
  and Middle East Eye timed out or could not connect. EU Council returned 403,
  Bangkok Post redirected to a payment-required response, Americas Quarterly
  returned 410, and the Eurostat, ABS, Mining Weekly, Renewables Now, European
  CDC and EastAfrican candidates returned 404.
- **Transport budget:** Liberty Street Economics and Just Security exceeded the
  app's size/time budget. No limits were weakened to admit them.
- **Duplicate:** the Al Jazeera candidate repeated an existing URL and was omitted.

These results apply to the tested URLs and environment, not every feed or
service a publisher offers. Recheck a replacement against the publisher's
current directory before adding it. The inherited catalog was not re-audited.
