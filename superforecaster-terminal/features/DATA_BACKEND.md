# DATA_BACKEND — Design

> A Rust backend that ingests every data source the BBRG Terminal needs,
> normalizes it into a canonical schema, and serves it to the SPA over REST
> and WebSocket with single-digit-millisecond hot-path latency.

---

## Contents

1. [Goal & non-goals](#1-goal--non-goals)
2. [Data inventory](#2-data-inventory)
3. [Architecture overview](#3-architecture-overview)
4. [Workspace layout](#4-workspace-layout)
5. [Canonical schema](#5-canonical-schema)
6. [Connector layer](#6-connector-layer)
7. [Per-source connector specs](#7-per-source-connector-specs)
   1. [Finnhub (US equity)](#71-finnhub-us-equity)
   2. [Binance (crypto)](#72-binance-crypto)
   3. [FX (Frankfurter + Twelve Data)](#73-fx-frankfurter--twelve-data)
   4. [FRED (Fed economic data)](#74-fred-fed-economic-data)
   5. [SEC EDGAR (filings)](#75-sec-edgar-filings)
   6. [Polymarket (prediction markets)](#76-polymarket-prediction-markets)
   7. [Kalshi (prediction markets)](#77-kalshi-prediction-markets)
   8. [BLS, BEA, ONS, Eurostat, e-Stat (macro)](#78-bls-bea-ons-eurostat-e-stat-macro)
   9. [Earnings & corporate actions calendars](#79-earnings--corporate-actions-calendars)
   10. [News wire + custom RSS](#710-news-wire--custom-rss)
   11. [Other free sources worth ingesting](#711-other-free-sources-worth-ingesting)
8. [Storage tier](#8-storage-tier)
9. [Hot path & caching](#9-hot-path--caching)
10. [API contract](#10-api-contract)
11. [Streaming protocol](#11-streaming-protocol)
12. [Backpressure & fan-out](#12-backpressure--fan-out)
13. [Auth, quotas, multi-tenant](#13-auth-quotas-multi-tenant)
14. [Observability](#14-observability)
15. [Reliability & SLOs](#15-reliability--slos)
16. [Deployment topology](#16-deployment-topology)
17. [Code quality — pedantic clippy + rustfmt](#17-code-quality--pedantic-clippy--rustfmt)
18. [Performance targets](#18-performance-targets)
19. [Phased rollout](#19-phased-rollout)
20. [Symbol & identifier universe](#20-symbol--identifier-universe)
21. [Time, market hours, holidays](#21-time-market-hours-holidays)
22. [Schema evolution & wire compatibility](#22-schema-evolution--wire-compatibility)
23. [Data quality, dedup, reconciliation](#23-data-quality-dedup-reconciliation)
24. [Connector control plane](#24-connector-control-plane)
25. [Idempotency & exactly-once writes](#25-idempotency--exactly-once-writes)
26. [Local development & secrets](#26-local-development--secrets)
27. [Cost estimates](#27-cost-estimates)
28. [Backup, restore, graceful shutdown](#28-backup-restore-graceful-shutdown)
29. [Open questions](#29-open-questions)

---

## 1. Goal & non-goals

### Goal

Build a Rust backend (`termd`) that is the *single source of truth* for every
panel in the BBRG Terminal UI. It must:

- **Ingest** every source listed in §2, on the right cadence per source
  (sub-second WebSocket for ticks, polling for slow REST feeds, on-demand
  for SEC filings).
- **Normalize** into a small set of canonical event types (§5) so the UI
  only ever speaks one schema regardless of upstream.
- **Index** for instant lookup by symbol, by sector, by tag, by free-text
  (filings, news headlines).
- **Serve** snapshots over REST and incremental deltas over a single
  multiplexed WebSocket per UI session.
- **Stay cheap** — small per-connection memory, zero allocation on the
  hot path, blanket use of `Bytes` and `Arc<str>` so the same payload is
  fanned out to every subscriber without copy.

The hot path budget is **≤ 1 ms** server-side from socket-recv to
socket-send (P99) for tick fan-out and **≤ 10 ms** for any cached snapshot
(P99). End-to-end (provider → browser DOM) target is **≤ 150 ms** for
real-time ticks.

### Non-goals

- Not a write-side OMS — the UI's Trade Ticket simulates fills against the
  same backend; we never route to actual venues.
- Not a complete data warehouse — the goal is "what the terminal needs",
  not a generic time-series store. Historical depth is **5 years** for
  daily bars, **30 days** for intraday minute bars, **48 hours** for
  tick-level prints.
- Not multi-region active-active in v1. Single region with hot-warm DR.

---

## 2. Data inventory

Every panel in the UI maps to one or more sources. The table below lists
**everything** the backend ingests, with cadence, source tier (free where
possible), licence shape, and the UI panel it lands in.

| Slice | Source | Free? | Auth | Cadence | UI panel(s) |
|---|---|---|---|---|---|
| US equity quotes (trade ticks) | **Finnhub WS** (`/trade`) | Free, 60 req/min for REST | API key | ~real time, sub-second | F3 EQTY, Ticker, F11 PORT marks |
| US equity intraday candles | **Finnhub** `/stock/candle` | Same | API key | On demand (cache 60 s) | F3 EQTY chart |
| US equity daily candles | **Finnhub** + **Tiingo** | Same | API key | Nightly | F3 EQTY chart (HP) |
| World equity indices | **Twelve Data** | Free 800/day | API key | Poll 10 s | F2 MKTS, Ticker |
| Crypto trades + L2 + funding | **Binance public WS** | Free | None | Real time | F3 EQTY (when active=crypto), F6 CMDTY (crypto) |
| Crypto reference (cap, vol) | **CoinGecko** | Free 50/min | None | Poll 60 s | F3 EQTY metadata |
| FX spot (G10) | **Frankfurter (ECB)** + **Twelve Data** | Free | None / key | Daily + 1 min | F2 MKTS, F5 FX |
| FX cross matrix | Derived from spot | — | — | On compute | F5 FX |
| US treasury yields | **FRED** + **U.S. Treasury Direct** | Free | API key (FRED) | Daily 16:30 ET + weekly auctions | F4 RATES, USYC curve |
| Central bank policy rates | **FRED** (incl. FOMC effective rate) + **BIS** + manual seed | Free | API key | Daily | F4 RATES, F8 CRED, F9 ECON |
| US macro (CPI, NFP, retail, etc.) | **BLS** + **BEA** + **FRED** | Free | API key | On release | F9 ECON |
| UK macro | **ONS** | Free | None | On release | F9 ECON |
| Eurozone macro | **Eurostat** + **ECB SDW** | Free | None | On release | F9 ECON |
| Japan macro | **e-Stat** | Free | API key | On release | F9 ECON |
| Other intl. macro | **OECD SDMX**, **World Bank** | Free | None | On release | F9 ECON |
| Economic calendar | **Finnhub** `/calendar/economic` + scraping fallback | Free | API key | Poll 5 min | F9 ECON |
| Earnings calendar + estimates | **Finnhub** `/calendar/earnings` + **EarningsWhispers** RSS | Free | API key | Poll 30 min | ERN |
| Corporate actions (div/split) | **SEC EDGAR Form 8-K** + **Nasdaq Trader** | Free | UA header (EDGAR) | Real time on filing | ERN, F3 EQTY |
| SEC filings (10-K, 10-Q, 8-K, S-1, etc.) | **SEC EDGAR JSON + Atom** | Free | UA header | Real time pub-sub (`/cgi-bin/browse-edgar?action=getcurrent`) | F3 EQTY (CN tab) |
| Insider transactions (Form 4) | **SEC EDGAR** | Free | UA header | Real time on filing | F3 EQTY |
| Institutional holdings (13F/13G) | **SEC EDGAR** | Free | UA header | Quarterly | F3 EQTY |
| IPO / S-1 pipeline | **SEC EDGAR** + **Nasdaq IPO calendar** | Free | UA header | Daily | ERN extension |
| Short interest | **FINRA** twice-monthly | Free | None | Bi-monthly | F3 EQTY |
| Halts | **NYSE** + **Nasdaq Trader RSS** | Free | None | Real time | Status bar |
| Options chains | **Yahoo Finance** unofficial + **Tradier sandbox** | Free | Key (Tradier) | Poll 60 s; on view force-refresh | F3 EQTY (OMON / OVDV) |
| Implied vol surface | Derived from chain | — | — | On request | OVDV |
| News (global wire) | **Finnhub** `/news` + **GDELT** + **Reuters/AP RSS** | Free | Key (Finnhub) | Real time + 60 s polls | F10 NEWS, F3 EQTY news |
| Custom RSS / Atom | **User-submitted URLs** | Free | None | Per-feed cadence (1–15 min) | F10 NEWS |
| Polymarket markets, trades, order books | **Polymarket CLOB** WS + REST | Free | None for read | Real time | New PMKT panel (proposed §7.6) |
| Kalshi events, markets, trades | **Kalshi** REST + WS | Free | API key + cert | Real time | New PMKT panel |
| Treasury auctions | **U.S. Treasury Direct** | Free | None | Weekly | F4 RATES |
| Commodities (energy) | **EIA** weekly STEO + spot | Free | API key | Weekly + daily | F6 CMDTY |
| Commodities (ags) | **USDA WASDE** RSS + spot via Yahoo | Free | None | Monthly + daily | F6 CMDTY |
| Weather (oil/ag overlay) | **NOAA NWS** + **OpenWeather** | Free | None / key | Hourly | F6 CMDTY callouts |
| Sentiment (Reddit) | **Reddit JSON** `r/wallstreetbets`, etc. | Free | None | Poll 5 min | F3 EQTY callouts |
| Stocktwits | **Stocktwits** REST | Free w/ cap | None | Poll 10 min | F3 EQTY callouts |
| FOMC dot plot, minutes | **Federal Reserve** RSS + scrape | Free | None | On release | F9 ECON |
| Halt reasons / Reg-SHO | **FINRA** + **SEC LULD** | Free | None | Real time | Status bar |
| Bond / CDS / IG-HY indices | **Mock** (paid otherwise) | — | — | — | F7 FI, F8 CRED |
| Equity Level-II depth | **Mock** for equities (paid otherwise); real for crypto via Binance | — | — | — | F3 EQTY depth |

Anything marked "Mock" remains served by the in-process `MockProvider`
behind the same canonical API, so the UI is oblivious. The boundary is
purely the connector implementation.

---

## 3. Architecture overview

```
                                  ┌─────────────────────────────────────────┐
                                  │           UI (React SPA)                │
                                  └───────────┬─────────────────────────────┘
                                              │ REST + WSS (multiplexed)
                                              ▼
                              ┌─────────────────────────────────────────────┐
                              │       termd-edge (Axum + tokio-tungstenite) │
                              │   - TLS termination, auth, rate limit       │
                              │   - WS multiplexer / subscription router    │
                              │   - REST snapshot endpoints (cached)        │
                              └───────────┬─────────────────────────────────┘
                                          │ NATS subjects (`tick.eq.NVDA`,
                                          │  `news.symbol.NVDA`, `edgar.10K`)
                                          ▼
       ┌──────────────────────────────────────────────────────────────────────────┐
       │                          NATS JetStream bus                              │
       └──┬──────────────┬──────────────┬─────────────┬──────────────┬────────────┘
          │              │              │             │              │
          ▼              ▼              ▼             ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌─────────────────┐
   │ ingest-eq  │ │ingest-crypto│ │ingest-news │ │ingest-fed│ │ ingest-edgar    │
   │ Finnhub WS │ │ Binance WS │ │RSS+GDELT+FH│ │FRED/BLS  │ │ SEC pub-sub +   │
   │ Tiingo, TD │ │ Coinbase   │ │ Reuters    │ │BEA/ONS/EU│ │ XBRL extraction │
   └────────────┘ └────────────┘ └────────────┘ └──────────┘ └─────────────────┘
          │              │              │             │              │
          │              │              │             │              │
          ▼              ▼              ▼             ▼              ▼
       ┌──────────────────────────────────────────────────────────────────────────┐
       │                       canonical-store (ClickHouse + PG + Tantivy)         │
       │   - ClickHouse: ticks, bars, time-series                                  │
       │   - Postgres:   filings, news, events, calendar, users                    │
       │   - Tantivy:    full-text over headlines + filings                        │
       │   - Redis:      hot snapshot cache, rate-limit counters                   │
       │   - Object storage (S3-compatible): raw filings, snapshot blobs           │
       └──────────────────────────────────────────────────────────────────────────┘
```

Two process tiers:

- **`termd-edge`** — what the UI talks to. Stateless. Authenticates, fans
  out from NATS to per-connection WS, serves REST snapshots from Redis or
  on miss from the canonical store. Horizontal scale-out behind an L4 LB
  (Fly.io anycast, Cloudflare TCP, or a plain HAProxy).
- **`termd-ingest-*`** — one binary per source family (or grouped by
  cadence/auth). Long-running, holds outbound WS, parses, normalizes,
  publishes canonical events onto NATS subjects. Writes durable copies to
  ClickHouse / Postgres / Tantivy / object storage.

NATS JetStream is the spine. Choosing it over Kafka:

- ~10× lighter operationally for our scale (single-node JetStream handles
  500k msg/s on commodity hardware).
- Built-in subject hierarchy is a perfect fit for `tick.eq.NVDA`,
  `tick.cx.BTCUSDT`, `news.symbol.NVDA`, `edgar.form.10K`.
- Native consumer groups + at-least-once delivery without Zookeeper.
- Rust client is mature (`async-nats`).

---

## 4. Workspace layout

`Cargo.toml` workspace at the repo root with one crate per concern. Each
crate has its own pedantic-clippy gate so a regression in `ingest-eq`
can't be papered over by `--allow` in the workspace root.

```
termd/
├── Cargo.toml                       # workspace
├── rustfmt.toml
├── clippy.toml
├── crates/
│   ├── termd-core/                  # canonical types, error, time, ids
│   ├── termd-bus/                   # NATS publish/subscribe wrappers, subject schema
│   ├── termd-store/                 # ClickHouse + Postgres + Tantivy + Redis abstractions
│   ├── termd-cache/                 # 3-tier cache (L0 task-local, L1 DashMap, L2 Redis)
│   ├── termd-proto/                 # WS frame definitions, REST DTOs, OpenAPI schemas
│   ├── termd-edge/                  # bin — Axum server, WS multiplexer
│   ├── termd-ingest-eq/             # bin — Finnhub/Tiingo/TD
│   ├── termd-ingest-crypto/         # bin — Binance/Coinbase
│   ├── termd-ingest-news/           # bin — Finnhub/GDELT/RSS/Reuters/Reddit
│   ├── termd-ingest-fed/            # bin — FRED/BLS/BEA/ONS/Eurostat/eStat
│   ├── termd-ingest-edgar/          # bin — SEC EDGAR live + backfill + XBRL
│   ├── termd-ingest-pmkt/           # bin — Polymarket + Kalshi
│   ├── termd-ingest-calendar/       # bin — earnings, econ, IPOs, halts
│   ├── termd-ingest-rss/            # bin — user-submitted feed runner
│   ├── termd-search/                # Tantivy index builder + query
│   ├── termd-xbrl/                  # lib — XBRL financials extractor (filing → facts)
│   ├── termd-cli/                   # bin — admin tool: replay, reindex, dump
│   └── termd-test/                  # lib — golden snapshots, deterministic harnesses
└── deploy/
    ├── docker/
    ├── nomad/   or   k8s/
    └── grafana/                     # dashboards JSON
```

Why this split:

- **One bin per source family** = one process to restart on credential
  rotation; one OOM doesn't take everything; each can be horizontally
  scaled independently (e.g. EDGAR is bursty around 4 PM ET earnings,
  while macro ingestors are mostly idle).
- **`termd-core`** is the only crate every other crate depends on
  directly. Keeps dependency graph a clean tree, not a mesh.
- **`termd-proto`** generates TypeScript types via `ts-rs` or `specta` so
  the React UI imports the same DTOs the Rust server emits — single
  source of truth for the wire schema.

---

## 5. Canonical schema

Every connector translates its source format into one of a small set of
canonical event types living in `termd-core::events`. The UI only ever
sees these shapes.

```rust
// crates/termd-core/src/events.rs

use bytes::Bytes;
use serde::{Deserialize, Serialize};
use smol_str::SmolStr;
use time::OffsetDateTime;

/// A symbol identifier, e.g. "NVDA US Equity", "BTCUSDT Crypto",
/// "EURUSD FX", "CL1 Comdty". 16-byte inline string (no heap).
pub type Symbol = SmolStr;

/// Source provenance — every event carries where it came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    Finnhub, Binance, Coinbase, Tiingo, TwelveData, Frankfurter,
    Fred, Bls, Bea, Ons, Eurostat, EStat, Oecd, WorldBank,
    SecEdgar, Polymarket, Kalshi, Eia, Usda, Noaa, Reddit, Stocktwits,
    Reuters, AP, Gdelt, UserRss, Mock,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Provenance {
    pub source: Source,
    /// Sequence number from the upstream feed if any. Used for dedup.
    pub seq: Option<u64>,
    /// Wall-clock time at the source (best-effort).
    pub src_ts: Option<OffsetDateTime>,
    /// Wall-clock time when we received it.
    pub ingest_ts: OffsetDateTime,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Event {
    /// A single tick (trade print). Crypto and equities both use this.
    Tick {
        symbol: Symbol,
        px: f64,
        qty: f64,
        side: Option<TradeSide>,
        provenance: Provenance,
    },

    /// Top-of-book / NBBO update.
    Quote {
        symbol: Symbol,
        bid: f64, bid_sz: f64,
        ask: f64, ask_sz: f64,
        provenance: Provenance,
    },

    /// Level-II depth delta or snapshot.
    DepthUpdate {
        symbol: Symbol,
        snapshot: bool,
        bids: Vec<DepthLevel>,
        asks: Vec<DepthLevel>,
        provenance: Provenance,
    },

    /// Aggregated bar (1m, 5m, 1h, 1d). Bars are stored, not streamed,
    /// unless the bar is "live" (open + currently updating).
    Bar {
        symbol: Symbol,
        interval: BarInterval,
        open: f64, high: f64, low: f64, close: f64, volume: f64,
        open_time: OffsetDateTime,
        provenance: Provenance,
    },

    /// A news headline.
    News {
        id: SmolStr,                  // provider id, dedup key
        headline: String,
        body: Option<String>,
        url: Option<String>,
        symbols: Vec<Symbol>,         // tagged symbols
        categories: Vec<SmolStr>,     // ECON, FX, EQ, FI, CMDTY, CRED, …
        sentiment: Option<Sentiment>, // computed in pipeline (FinBERT or similar)
        published: OffsetDateTime,
        provenance: Provenance,
    },

    /// An economic calendar item (release).
    EconEvent {
        id: SmolStr,
        time: OffsetDateTime,
        ccy: SmolStr,                 // "USD", "EUR", …
        label: String,                // "CPI YoY"
        importance: u8,               // 1..3
        forecast: Option<String>,
        previous: Option<String>,
        actual: Option<String>,
        provenance: Provenance,
    },

    /// An SEC EDGAR filing index entry. Body is in `termd-store` blob.
    Filing {
        accession: SmolStr,           // 0000320193-25-000058
        cik: u64,
        company: String,
        form: SmolStr,                // 10-K, 10-Q, 8-K, S-1, 4, 13F-HR
        filed: OffsetDateTime,
        period: Option<OffsetDateTime>,
        primary_doc_url: String,
        symbols: Vec<Symbol>,
        provenance: Provenance,
    },

    /// XBRL-extracted financial facts (revenue, eps, etc.) attached to
    /// a filing. Emitted asynchronously after the filing event.
    FilingFacts {
        accession: SmolStr,
        facts: Vec<XbrlFact>,         // (concept, value, unit, period)
        provenance: Provenance,
    },

    /// Insider transaction (Form 4 row).
    InsiderTrade {
        accession: SmolStr,
        cik: u64,
        symbol: Symbol,
        person: String,
        relationship: SmolStr,        // CEO, CFO, Director, …
        side: TradeSide,
        shares: f64,
        price: Option<f64>,
        traded: OffsetDateTime,
        provenance: Provenance,
    },

    /// Prediction-market quote (Polymarket / Kalshi).
    PredictionQuote {
        venue: Source,
        market_id: SmolStr,
        question: String,
        outcome: SmolStr,             // YES / NO, or specific outcome
        bid: f64, ask: f64, last: f64,
        volume: f64,
        resolved: bool,
        resolution: Option<SmolStr>,
        provenance: Provenance,
    },

    /// Time-series datapoint from a macro source.
    Series {
        id: SmolStr,                  // FRED series id, BLS series id, etc.
        time: OffsetDateTime,
        value: f64,
        unit: SmolStr,
        provenance: Provenance,
    },

    /// Operational state (halts, circuit breakers).
    Status {
        symbol: Option<Symbol>,
        code: SmolStr,                // LULD-T1, HALT, RESUME, …
        message: String,
        provenance: Provenance,
    },
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TradeSide { Buy, Sell, Unknown }

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum BarInterval { M1, M5, M15, H1, D1 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DepthLevel { pub px: f64, pub qty: f64 }

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Sentiment { Positive, Neutral, Negative, Alert }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct XbrlFact {
    pub concept: SmolStr,             // us-gaap:Revenues
    pub value: f64,
    pub unit: SmolStr,                // USD, shares
    pub period_start: Option<OffsetDateTime>,
    pub period_end:   Option<OffsetDateTime>,
}
```

Notes on the schema design:

- **`SmolStr`** (24-byte inline) for any string ≤ 23 chars (symbols,
  source ids, accession numbers). Avoids heap for the hot path. Use
  `String` only for headline / body / URL.
- **`Symbol` is a `SmolStr` alias here for brevity, but in production
  it resolves through a `SymbolRef` with class + venue + alias map —
  see §20.** Connectors normalize venue-specific identifiers to the
  canonical form before emitting events.
- **Time is UTC, period.** Every `OffsetDateTime` constructor in the
  codebase uses `time::OffsetDateTime::now_utc()` or parses with an
  explicit UTC interpretation. Local-time formatting is a UI concern;
  see §21 for the session-state module that drives market-hours logic.
- **`f64` everywhere** for numbers — every upstream feed gives us
  `f64`-or-narrower, and `f64`'s 15-17 significant decimal digits cover
  every legal NMS price and every Binance crypto quantity. Equality on
  `f64` is forbidden by `clippy::float_cmp`; comparisons go through
  `approx::AbsDiffEq` or an explicit epsilon. If we ever maintain our
  own books at fractional cents, we'll introduce a `Money(Decimal)`
  newtype behind a type migration — the JSON wire format already
  round-trips safely below 2^53. Justification in §5.3-equivalent
  discussion lives in §22.
- **`provenance` on every variant** — non-negotiable. Every downstream
  consumer (UI, alerting, backtests) can prove where a value came from
  and at what receive-time, without ever having to back-chain through
  storage.
- **`Bytes` is the on-the-wire payload type** post-serialization. The
  serializer (`rmp-serde` / MessagePack) produces a single `Bytes`
  that's cheaply cloned to N subscribers.
- **Envelope version** — every wire frame carries a `version: u16`
  field added at the bus layer (see §22). Old consumers refuse to
  deserialize newer envelopes deterministically rather than producing
  wrong values.

---

## 6. Connector layer

Every ingestor implements a single trait, parameterised by event type
and configuration. The runtime hands it a publisher, the connector
emits canonical events.

```rust
// crates/termd-core/src/connector.rs

#[async_trait::async_trait]
pub trait Connector: Send + Sync {
    /// Stable identifier; appears in metrics + logs.
    fn name(&self) -> &'static str;

    /// Single startup point. Implementations should return only on
    /// permanent failure; transient errors must be handled internally
    /// with backoff.
    async fn run(self: Arc<Self>, ctx: ConnectorCtx) -> Result<()>;

    /// Optional health probe; default uses last-event-received timestamp.
    fn health(&self) -> Health { Health::default() }
}

pub struct ConnectorCtx {
    pub bus: Arc<dyn EventBus>,            // publish into NATS
    pub store: Arc<dyn Store>,             // optional durable write
    pub clock: Arc<dyn Clock>,             // injectable for tests
    pub shutdown: CancellationToken,
    pub metrics: ConnectorMetrics,
}
```

Common machinery (in `termd-core::connector::runtime`):

- **Exponential-backoff supervisor** — restart on `run()` exit, capped
  at 60 s, jittered. Crash-loop detection (>5 restarts in 60 s) flips
  the connector to `Degraded` and stops auto-restart until a manual
  reset.
- **Token-bucket rate limiter** per source's documented quota, sourced
  from a `ConnectorConfig`. The connector calls `rate.acquire(cost)`
  before every outbound HTTP/WS frame so the limiter can't be bypassed.
- **Dedup window** — every connector pipes events through a small
  `BTreeMap<DedupKey, Instant>` with TTL eviction, keyed by source-stable
  identifiers (accession number, news GUID, trade `id`). Drops late
  duplicates from retry/replay paths.
- **Schema validation** — events run through a `validate()` pass that
  is `debug_assert!` in release (zero cost) and explicit in tests.

### Connector shape — REST poller

```rust
pub struct RestPoller<F> {
    cfg: PollerCfg,
    fetch: F,
}

impl<F, Fut, T> Connector for RestPoller<F>
where
    F: Fn(&PollerCfg) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = Result<T>> + Send + 'static,
    T: IntoEvents + Send + 'static,
{
    async fn run(self: Arc<Self>, ctx: ConnectorCtx) -> Result<()> {
        let mut interval = tokio::time::interval(self.cfg.period);
        loop {
            tokio::select! {
                _ = ctx.shutdown.cancelled() => return Ok(()),
                _ = interval.tick() => {
                    match (self.fetch)(&self.cfg).await {
                        Ok(t) => {
                            for ev in t.into_events() { ctx.bus.publish(ev).await?; }
                        }
                        Err(e) => tracing::warn!(error = ?e, "poll failed"),
                    }
                }
            }
        }
    }
}
```

### Connector shape — WebSocket stream

```rust
pub struct WsStream { cfg: WsCfg, mapper: Arc<dyn FrameMapper> }

impl Connector for WsStream {
    async fn run(self: Arc<Self>, ctx: ConnectorCtx) -> Result<()> {
        let mut backoff = ExpBackoff::default();
        loop {
            match self.connect_once(&ctx).await {
                Ok(()) => backoff.reset(),
                Err(e) => {
                    tracing::warn!(error = ?e, "ws disconnect");
                    tokio::time::sleep(backoff.next()).await;
                }
            }
            if ctx.shutdown.is_cancelled() { return Ok(()); }
        }
    }
}
```

`connect_once` opens the socket, sends the subscription frames, and runs
the receive loop. The receive loop pushes each frame through
`FrameMapper::map(frame) -> Vec<Event>` and the resulting events go on
the bus. A heartbeat task pings the socket every 25 s and tears down on
no-pong.

---

## 7. Per-source connector specs

### 7.1 Finnhub (US equity)

**REST** (`finnhub.io/api/v1`)

- `/quote?symbol=NVDA` — snapshot quote
- `/stock/candle?symbol=NVDA&resolution=1&from=...&to=...` — bars
- `/stock/profile2` — issuer profile, country, ipo
- `/calendar/economic` — econ calendar
- `/calendar/earnings` — earnings
- `/news?category=general` — wire
- `/company-news?symbol=NVDA` — per-symbol news

**WebSocket** (`wss://ws.finnhub.io?token=...`)

- Send `{"type":"subscribe","symbol":"NVDA"}` per symbol.
- Receive `{"type":"trade","data":[{"s":"NVDA","p":142.84,"v":100,"t":1700000000000,"c":[]}]}`
- Heartbeat: server sends `{"type":"ping"}` periodically; we reply `{"type":"pong"}`.
- 50-symbol cap on free tier — handle by subscribing only to the
  union of currently-watched symbols across all connected UI clients.

**Connector behavior**

- One singleton WS per backend node. UI subscriptions translate to
  Finnhub subscriptions with reference counting; symbols with zero
  subscribers are unsubscribed after a 60-second grace.
- Outbound rate limit: 30 frames/s, well below the documented cap.
- Bars: REST with a 60-second TTL cache, served via `Bar` events
  pushed onto `bar.eq.<symbol>.1m`.
- News: REST poll every 60 s; dedup on `id` field.

### 7.2 Binance (crypto)

**WebSocket** (`wss://stream.binance.com:9443/stream?streams=btcusdt@trade/btcusdt@depth20@100ms`)

- Combined streams (`/stream?streams=...`) — one TCP connection serves
  every subscribed symbol.
- `@trade` for ticks, `@depth20@100ms` for top-20 L2 at 100 ms cadence,
  `@markPrice` for perp funding rate (`fapi`).
- Snapshot via REST first, then apply deltas — Binance's documented
  pattern, otherwise the book becomes inconsistent within minutes.
- No auth needed for public streams; rate limit is 5 connections per
  300 s and 24 hours connection lifetime.

**Connector behavior**

- Maintain a `L2Book` per symbol in-process. Snapshot on subscribe,
  apply deltas in `u/U` sequence order, drop deltas where `U <= lastUpdateId`,
  resync on gap.
- Emit `DepthUpdate { snapshot: true, ... }` on first subscribe and
  `DepthUpdate { snapshot: false, ... }` on each delta.
- Trades published one-to-one as `Tick` events.

### 7.3 FX (Frankfurter + Twelve Data)

- **Frankfurter** is the daily ECB reference rate — only useful for
  end-of-day FX. Free, CORS-friendly, no key.
- **Twelve Data** provides minute bars and a `forex_quote` WS for
  intraday — free tier has 800 req/day and 8 concurrent symbols on WS.
- Strategy: poll Twelve Data every 30 s for the 8 most-watched G10
  pairs, fall through to Frankfurter for less-watched pairs and the
  end-of-day reference rate. Cross rates computed deterministically
  from spots, not fetched.

### 7.4 FRED (Fed economic data)

- `https://api.stlouisfed.org/fred/series/observations?series_id=DGS10`
- API key, generous limits (120k req/day quoted).
- Each series mapped to a `Series` event. Maintain a static catalog
  in `termd-ingest-fed/data/series.toml` describing each series id, its
  canonical alias, units, frequency.
- Poll cadence: hourly for fast-moving series (yields), daily for
  slow ones (employment, GDP).

### 7.5 SEC EDGAR (filings)

EDGAR is the highest-effort connector — the entire workflow is built
around it because filings are bursty (200+ 10-Ks land in the same hour
during peak season) and the data is structurally rich (XBRL).

**Live feed**

- `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&company=&datea=&dateb=&owner=include&count=40&output=atom`
- Poll every 15 s during market hours, every 60 s otherwise.
- `User-Agent: BBRG-Term termd@example.com` — EDGAR requires a real
  contact; without it requests 403.
- Output is Atom — parse with `quick-xml`.

**Document fetch**

- For each new accession, fetch `/Archives/edgar/data/{cik}/{accession-nodashes}/{accession}-index.json`
- Find `primary_document` and download into S3 (`s3://termd-filings/{cik}/{accession}/raw.htm`)
- Emit a `Filing` event immediately with the index metadata.

**XBRL extraction** (async pipeline)

- For 10-K / 10-Q / 8-K / 6-K, fetch the `.xml` XBRL instance.
- Use `xbrl-rs` (or roll an XPath-based extractor in `termd-xbrl`)
  to pull `us-gaap:Revenues`, `us-gaap:NetIncomeLoss`,
  `us-gaap:EarningsPerShareDiluted`, etc.
- Emit `FilingFacts { accession, facts }`.

**Symbol mapping**

- CIK → ticker via the SEC's `company_tickers.json` (refresh daily).
- Ticker → CIK reverse lookup cached in Redis.

**Form 4 / insider trades**

- Form-4 XML has standardised columns. Extract per-row
  `InsiderTrade` events. These are valuable for the F3 EQTY tab.

**13F-HR**

- Quarterly. Parse the holdings table from the XML. Persist to
  Postgres as a holdings snapshot per CIK per quarter.

**Backfill**

- `termd-cli backfill edgar --since 2024-01-01 --forms 10-K,10-Q,8-K,4,13F-HR`
- Walks the daily index files at
  `https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/full-index.json`.
- Throttled at 10 req/s per EDGAR's terms.

### 7.6 Polymarket (prediction markets)

- **CLOB REST**: `https://clob.polymarket.com`
  - `GET /markets` — paginated catalog
  - `GET /book?market=<id>` — order book
  - `GET /trades?market=<id>` — recent trades
  - `GET /price?token_id=<id>` — best bid/ask
- **WebSocket**: `wss://clob.polymarket.com/ws`
  - Subscribe to `user` (auth), `market` (public): `{"type":"market","markets":["<id>"]}`
  - Receives `book`, `last_trade_price`, `tick_size_change`.
- **On-chain settlement** lives on Polygon. We don't read on-chain
  directly in v1; CLOB API is sufficient for live state. Future: a
  fallback connector that queries Polygon RPC for resolution events
  when a market closes.

**Event mapping**

- `PredictionQuote { venue: Polymarket, market_id, question, outcome: YES, bid, ask, last, volume, resolved: false }`
- New panel `PMKT` (proposed) in the UI consumes `prediction.poly.*` and
  `prediction.kalshi.*` subjects.

### 7.7 Kalshi (prediction markets)

- **REST**: `https://trading-api.kalshi.com/trade-api/v2`
  - `GET /events`, `GET /markets`, `GET /trades`, `GET /orderbook`
  - Auth: client cert + API key; required for everything except public market metadata.
- **WebSocket**: `wss://trading-api.kalshi.com/trade-api/ws/v2`
  - Subscribe with `{"id":1,"cmd":"subscribe","params":{"channels":["ticker"],"market_tickers":["..."]}}`

**Connector behavior**

- A single connection per node, subscribe to currently-watched markets
  with ref-counting (as with Finnhub).
- Map to `PredictionQuote` events with `venue: Kalshi`.

### 7.8 BLS, BEA, ONS, Eurostat, e-Stat (macro)

All of these are batch REST APIs that publish on a fixed calendar.

| Agency | Endpoint | Auth | Frequency |
|---|---|---|---|
| **BLS** (US Bureau of Labor Statistics) | `https://api.bls.gov/publicAPI/v2/timeseries/data/` | Optional key (500/day) | Monthly releases |
| **BEA** (US Bureau of Economic Analysis) | `https://apps.bea.gov/api/data` | Required key, generous limit | Quarterly GDP, monthly PCE |
| **ONS** (UK Office for National Statistics) | `https://api.ons.gov.uk/dataset/` | None | Monthly |
| **Eurostat** | `https://ec.europa.eu/eurostat/api/dissemination/statistics` | None | Monthly/quarterly |
| **e-Stat** (Japan) | `https://api.e-stat.go.jp/rest/3.0/app/` | API key | Monthly |
| **OECD SDMX** | `https://sdmx.oecd.org/public/rest/data/` | None | Quarterly |
| **World Bank** | `https://api.worldbank.org/v2/` | None | Annual |

**Connector behavior**

- A shared `termd-ingest-fed` binary with one async task per agency.
- Each task is a `RestPoller` with a per-agency cron schedule that
  matches the publication calendar (e.g., BLS NFP at 08:30 ET first
  Friday of each month — poll every 5 minutes in a 60-minute window
  around that, otherwise daily).
- Each datapoint emitted as a `Series` event with a canonical
  `id` (e.g., `bls.LNS14000000` → unemployment rate).
- A static **alias table** maps these to UI-friendly names ("US
  Unemployment Rate") and to the relevant econ-calendar entries.
- Surprise computation (`actual - forecast`) happens in the calendar
  pipeline, not here.

### 7.9 Earnings & corporate actions calendars

- **Earnings**: Finnhub `/calendar/earnings` + earningswhispers RSS for
  the "implied move" field that's hard to get for free.
- **Corporate actions**: EDGAR Form 8-K item 8.01 + Nasdaq Trader
  dividend/split files.
- **IPO calendar**: Nasdaq IPO calendar API + EDGAR S-1 stream.
- All emitted as `EconEvent` or a new `CalendarEvent` variant.

### 7.10 News wire + custom RSS

**Wire**

- **Finnhub** general + per-symbol — primary.
- **GDELT** Global Knowledge Graph — secondary, very wide coverage,
  noisy. Used for tagging and discovery rather than headlines.
- **Reuters TopNews RSS** + **AP**'s public feeds + **Yahoo Finance
  RSS** per symbol — backup.

**Custom RSS** (`termd-ingest-rss`)

User-submitted feeds, configured per-user. The shape:

```
POST /api/v1/users/{uid}/rss
{
  "name": "FT — Markets",
  "url": "https://www.ft.com/markets?format=rss",
  "categories": ["markets", "FT"],
  "poll_secs": 300,
  "symbol_tagging": "auto"  // or "off" or a manual list
}
```

The `termd-ingest-rss` worker:

1. Pulls active feed configs from Postgres on startup, refreshes every
   minute.
2. Schedules each feed on its own tokio task with its own cadence.
3. Fetches with `If-Modified-Since` + `ETag` to be polite.
4. Parses with `feed-rs` (handles RSS 0.9, RSS 1.0, RSS 2.0, Atom,
   JSON Feed).
5. Dedups against the last 7 days of `News.id` (provider GUID or URL).
6. Auto-tags symbols by running headlines through a small Aho-Corasick
   matcher built from the ticker + company-name corpus.
7. Emits `News` events on `news.user.<uid>.<feed_id>` so the user only
   sees their feeds, plus on `news.global` for the shared wire when the
   feed is publicly shared.

The UI's NEWS screen surfaces user feeds as additional categories
alongside TOP/ECON/FX/EQ/FI/CMDTY/CRED.

### 7.11 Other free sources worth ingesting

| What | Why | Source |
|---|---|---|
| **U.S. Treasury auctions** | Auction results inform F4 RATES (bid-to-cover, tail) | TreasuryDirect Securities API |
| **FOMC press releases / statements** | Headlines for F9 ECON | federalreserve.gov RSS |
| **EIA** weekly petroleum status | F6 CMDTY energy panel | EIA Open Data API |
| **USDA** WASDE | F6 CMDTY ags panel | USDA RSS + JSON |
| **NOAA** alerts | Weather overlay for cmdty | api.weather.gov |
| **NYSE/Nasdaq halts** | Status-bar pill, alerts | nasdaqtrader.com/RPCService |
| **FINRA** short interest | F3 EQTY callouts | FINRA bi-monthly file |
| **Reddit** r/wallstreetbets, r/investing | Sentiment chips on F3 | reddit.com/.json |
| **Stocktwits** | Per-symbol sentiment | api.stocktwits.com |
| **Crypto on-chain** (Etherscan, etc.) | Whale txns, gas, mempool | Etherscan free tier |

All of these are low-traffic, free-tier-friendly, and slot into the same
`Connector` trait. None requires bespoke architecture beyond what's
already described.

---

## 8. Storage tier

Four backing stores, each chosen because the alternatives are worse for
that specific access pattern.

### 8.1 ClickHouse — time-series

- **Schema**:

  ```sql
  CREATE TABLE ticks (
      symbol     LowCardinality(String),
      ts         DateTime64(6),
      px         Float64,
      qty        Float64,
      side       Enum8('B'=1, 'S'=-1, 'U'=0),
      source     LowCardinality(String)
  ) ENGINE = MergeTree
  PARTITION BY toYYYYMMDD(ts)
  ORDER BY (symbol, ts)
  TTL ts + INTERVAL 48 HOUR DELETE;

  CREATE TABLE bars (
      symbol     LowCardinality(String),
      interval   LowCardinality(String),
      open_time  DateTime,
      open       Float64,
      high       Float64,
      low        Float64,
      close      Float64,
      volume     Float64
  ) ENGINE = ReplacingMergeTree
  PARTITION BY toYYYYMM(open_time)
  ORDER BY (symbol, interval, open_time);

  CREATE TABLE series (
      id      LowCardinality(String),
      ts      DateTime,
      value   Float64,
      unit    LowCardinality(String)
  ) ENGINE = ReplacingMergeTree
  PARTITION BY toYYYY(ts)
  ORDER BY (id, ts);
  ```

- ClickHouse handles **billions of ticks** with sub-second range
  scans because of the `ORDER BY (symbol, ts)` primary and the
  partition pruning. A symbol's last 6.5h of ticks (one trading day)
  is ≤ 2 ms to scan.
- We write in **batches of 1k rows or every 250 ms**, whichever first,
  via the official `clickhouse-rs` client's async inserter.
- TTL drops tick-level data after 48 h — bars and series are kept
  longer.

### 8.2 Postgres — structured & metadata

- **Tables**:
  - `users`, `sessions`, `api_keys`
  - `watchlists`, `watchlist_symbols`
  - `rss_feeds` (per-user feed configs)
  - `alerts` (persisted alerts so they survive restarts; the in-RAM
    alert engine hot-loads on boot)
  - `orders`, `fills`, `positions` (simulated OMS — the chat tool can
    fire `place_order` and we record it)
  - `filings` (`accession PK, cik, company, form, filed, period, primary_doc_url, status`)
  - `filing_facts` (denormalised XBRL: `accession, concept, value, unit, period_start, period_end`)
  - `insider_trades`
  - `holdings_13f` (`cik, quarter, holding (nameOfIssuer, cusip, value, shares, putCall, investmentDiscretion)`)
  - `news_index` (`id PK, headline, url, published, source, sentiment, categories, symbols[]`)
  - `econ_events`, `corporate_actions`
- Postgres 16, partitioned by month on `filings` and `news_index`.
- All access through SQLx with `sqlx::query!` compile-time-checked
  queries against a snapshot schema in CI.

### 8.3 Tantivy — full-text search

- One **searcher per index**: `news`, `filings`, `symbols`.
- Filings index pulls plain text from XBRL + HTML stripping via
  `lol-html`. Filed daily; merge segments nightly.
- Used to power the UI's command palette (symbol fuzzy + headline
  search) and a `SEARCH` panel.

### 8.4 Redis — hot cache + ephemeral

- Last quote per symbol (`q:<symbol>` → MessagePack `Quote`, TTL 5 min,
  refreshed on every Quote event).
- Last 100 ticks per active symbol (Redis Streams `tx:<symbol>` capped
  at 100).
- Rate-limit counters per API key.
- WS session state (per-user subscriptions list — for sticky
  reconnection across edge restarts).
- Pub/sub for **edge → edge** cache invalidation; main fan-out is on
  NATS.

### 8.5 Object storage

- S3-compatible (Cloudflare R2 to avoid egress charges).
- Raw filings (HTM/PDF/XML).
- Daily snapshot blobs (compressed MessagePack archive of the whole
  market at 16:00 ET) — used for backtest replay and cold-start
  hydration.

---

## 9. Hot path & caching

Three cache tiers in the edge process. The hot path of a UI subscription
is: NATS deliver → cache write (L1) → fan out to N WS connections.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ L0  per-task                                                              │
│   - thread-local buffer for the *currently-handled* HTTP request          │
│   - 0 alloc, cleared at request end                                       │
├───────────────────────────────────────────────────────────────────────────┤
│ L1  in-process (DashMap<Symbol, Arc<Snapshot>>)                           │
│   - last quote / last bar / last news headline per symbol                 │
│   - <50 µs read; bounded at ~100k symbols × ~5 entries per symbol         │
├───────────────────────────────────────────────────────────────────────────┤
│ L2  Redis                                                                 │
│   - same data shape, shared across edge nodes                             │
│   - <500 µs read over a unix-socket-attached sidecar Redis                │
├───────────────────────────────────────────────────────────────────────────┤
│ L3  ClickHouse / Postgres / Tantivy / S3                                  │
│   - cold path; only on full miss (e.g. first-ever query for a symbol)     │
└───────────────────────────────────────────────────────────────────────────┘
```

**Write-through pattern**: when an event lands from NATS, the connector
edge updates L1 directly (a `DashMap::insert` with `Arc::clone` of the
event payload), then asynchronously fires the same value to Redis via
`mpsc` to a small writer task. The WS fan-out reads from L1 only —
Redis is **not** in the hot path, it's only there for cross-node hydration
on cold start.

**Snapshot endpoints** (REST) try L1 → L2 → L3 in order. P50 hits on
L1; we still record cache miss rates per-symbol to spot anomalies.

**Bytes-everywhere**: events are serialized once in MessagePack
(`rmp-serde`) into a `Bytes`, stored in `Arc<Bytes>` in L1, and the WS
fan-out is `Bytes::clone` (refcount bump) → `WebSocket::send(...)`. Zero
copy in the steady state.

---

## 10. API contract

REST is for snapshots and operations. WS is for streams.

### 10.1 REST (Axum)

All endpoints rooted at `/api/v1`. JSON only.

```
GET  /quote/{symbol}                       last quote
GET  /chart/{symbol}?interval=1m&span=1d   OHLCV bars
GET  /depth/{symbol}                       L2 snapshot
GET  /trades/{symbol}?limit=100            recent trades
GET  /options/{symbol}?expiry=20JUN26      option chain
GET  /vol-surface/{symbol}                 expiry × strike × IV grid
GET  /news?cat=&symbol=&since=&limit=      news wire
GET  /events/economic?ccy=&imp=&from=&to=  econ calendar
GET  /events/earnings?from=&to=            earnings calendar
GET  /filings?cik=&form=&from=&to=         filings index
GET  /filings/{accession}                  single filing + facts
GET  /insider/{symbol}                     insider trades
GET  /macro/series/{id}?from=&to=          FRED/BLS/BEA series
GET  /prediction/markets?venue=            polymarket / kalshi catalog
GET  /prediction/markets/{id}              market state + book
GET  /watchlists/{id}                      user watchlist
POST /orders                               place simulated order
GET  /positions                            current positions
POST /alerts                               create alert
GET  /alerts                               list alerts
POST /users/me/rss                         add custom RSS feed
GET  /users/me/rss                         list user feeds
```

All responses carry an `etag` header and support conditional `If-None-Match`.

### 10.2 Errors

`application/problem+json` (RFC 7807):

```json
{ "type":"https://termd/errors/symbol-not-found",
  "title":"Symbol not found",
  "status":404,
  "detail":"No symbol named ZZZZ",
  "instance":"/quote/ZZZZ" }
```

### 10.3 Schema generation

The `termd-proto` crate uses `utoipa` to derive OpenAPI from typed
handlers, and `ts-rs` to emit a `.d.ts` file the React app imports.
Same source-of-truth structs as the WS frames.

---

## 11. Streaming protocol

**One WebSocket per UI session**. The client subscribes to channels
inside the socket — no second connection, no per-symbol socket.

### 11.1 Connection handshake

The WS upgrade carries an explicit version in the
`Sec-WebSocket-Protocol` header:

```
Sec-WebSocket-Protocol: bbrg.v1
```

The server echoes the selected version. Future breaking changes ship
as `bbrg.v2`; we promise to keep accepting `bbrg.v1` for at least one
minor release after `v2` ships. Clients that omit the header are
treated as `bbrg.v1` for now.

Max frame size is **4 MiB** (`tokio-tungstenite`'s `max_message_size`).
Anything larger is server-side an internal error — we never need
frames that big, and a runaway producer should crash before a slow
client OOMs.

### 11.2 Frame format

```
Binary frames, MessagePack-encoded `WireFrame`:

WireFrame {
  version: u16            // wire envelope version; bumped on breaking change
  enum: "snapshot" | "delta" | "ack" | "err" | "ping" | "pong" | "sub" | "unsub"
  channel: string         // "quote.NVDA", "news.symbol.NVDA", "prediction.poly.<id>"
  seq: u64                // server-assigned monotonic per-channel
  payload: bytes          // MessagePack-encoded Event variant
}
```

### 11.3 Subscribe handshake

```
client → server: { type: "sub", channels: ["quote.NVDA", "depth.NVDA", "news.symbol.NVDA"] }
server → client: { type: "ack", channels: [...], cursors: { "quote.NVDA": 0 } }
server → client: { type: "snapshot", channel: "quote.NVDA", seq: 0, payload: <Quote> }
server → client: { type: "delta", channel: "quote.NVDA", seq: 1, payload: <Quote> }
...
```

**Snapshot before deltas** for stateful channels (`quote`, `depth`,
`position`, `alerts`). For stateless channels (`tick`, `news`) we skip
the snapshot.

### 11.4 Heartbeat

- Server sends `ping` every 25 s.
- Client expected to `pong` within 10 s, else server closes with
  `WS_TIMEOUT (4001)`.

### 11.5 Reconnect / resume

- The client passes the last `seq` it saw per channel in the `sub` frame
  as `{ cursors: { "quote.NVDA": 1234 } }`.
- The server replays from `seq+1` onwards from a per-channel ring buffer
  (in Redis Streams, capped at 1k entries).
- If the cursor is older than the ring's earliest, the server sends a
  fresh snapshot and resets the seq.

### 11.6 Compression

- `permessage-deflate` on by default.
- For the JSON-equivalent payload sizes we see (< 250 B per tick) the
  win is marginal but it cuts dashboards 4×.

### 11.7 Backpressure & close codes

- Each WS connection has a bounded `mpsc::channel(256)` between the
  router task and the writer task.
- If the channel fills (slow client), the router **drops** all but the
  latest `snapshot` per channel and sends a single `err`
  `BACKPRESSURE_OVERFLOW` so the client can `sub` again to resync.
- This is the right default for a market terminal: a slow client wants
  the latest state, not a full history.

Close codes used:

| Code | Meaning |
|---|---|
| 1000 | Normal closure (client logout) |
| 1001 | Going away (page navigation) |
| 1012 | Service Restart — clients reconnect with cursors |
| 4001 | Server-initiated timeout (no pong within 10 s) |
| 4002 | Authentication invalidated (key rotated, JWT expired) |
| 4003 | Quota exceeded — too many channels |
| 4004 | Protocol version unsupported — upgrade client |
| 4090 | Server overloaded — back off with jitter |

---

## 12. Backpressure & fan-out

The fan-out path looks like:

```
NATS subject (e.g. tick.eq.NVDA)
  │
  ▼
edge-router task per connection (subscribes to channels-of-interest)
  │
  ▼
per-connection bounded mpsc::Sender<Bytes>
  │
  ▼
writer task → WebSocket::send(Bytes)
```

Important properties:

- **NATS** does its own fan-out. We don't run a single big subscription
  per node and dispatch in-app; each connection's router has its own
  subscription with the union of its channels, so NATS knows the
  per-connection interest set.
- **`Bytes` clone is `Arc::clone`** — fanning out a 200-byte tick to 1
  000 subscribers is 1000 atomic increments, not 1000 200-byte copies.
- **Backpressure isolates one slow client from the rest**: a bounded
  mpsc per connection means a stuck WS doesn't back-stuff the NATS
  consumer, only its own queue.

Capacity math (single edge node):

- 50 000 concurrent WS sessions
- 25 ticks/s aggregate per session (median UI subscribes to ~10 symbols
  with ~2-3 ticks/s)
- 200 B per tick after MessagePack
- 50 000 × 25 × 200 B = **250 MB/s egress** sustained
- At 10 Gbit/s NIC = 1.25 GB/s, we're at 20 % NIC, plenty of headroom.

---

## 13. Auth, quotas, multi-tenant

- **Authentication**: JWT (HS256) issued by a thin `termd-auth` service
  that handles signup, password, OAuth (Google/GitHub). Tokens carry
  `sub`, `tier`, `quota_id`, `exp`.
- **API keys**: per-user issued from a settings page, `tk_<base58>`,
  hashed with Argon2id in the DB. Used for programmatic access from
  CLI / scripts; presented as `Authorization: Bearer tk_...`.
- **Quotas**:
  - REST: 60 req/s burst, 1k/min sustained — Redis token bucket.
  - WS subscriptions: 200 channels per session for free tier, 2 000 for
    pro.
  - User RSS feeds: 20 per user, 5-minute minimum poll period.
- **Tenant isolation**: every event is published on a public subject by
  default, but **per-user** events (positions, orders, alerts, RSS) are
  published on `user.<uid>.*` subjects. A router refuses to subscribe a
  connection to another user's subjects — enforced both in the
  permissions check and by NATS account boundaries.

---

## 14. Observability

- **Tracing**: `tracing` + `tracing-subscriber` + `tracing-opentelemetry`,
  exported to Tempo / Jaeger via OTLP.
- **Metrics**: `metrics` crate + `metrics-exporter-prometheus`. Standard
  histograms for every hot path:
  - `connector.events.published_total{source}`
  - `connector.events.duplicate_total{source}`
  - `connector.reconnect_total{source}`
  - `edge.ws.connections`
  - `edge.ws.fanout_lag_seconds` (histogram)
  - `edge.ws.backpressure_drops_total`
  - `cache.hit_total{tier}` / `cache.miss_total{tier}`
  - `db.query.duration_seconds{op,table}`
- **Logs**: JSON to stdout, parsed by Vector / Loki. Each log line has
  `trace_id`, `span_id`, `connector`, `symbol` where applicable.
- **Health**: `/healthz` (liveness) + `/readyz` (every connector reports
  last-event-received age; readyness = all primary sources < 60 s old
  for tick feeds, < 5 min for slow feeds).
- **Synthetic probes**: a black-box prober that subscribes to a known
  channel, asserts a tick within 5 s during market hours, alerts
  PagerDuty otherwise.

Grafana dashboards (`deploy/grafana/`):

- **Overview**: edge connections, NATS msg/s, p50/p95/p99 fan-out lag,
  error rates per connector.
- **Per-source**: events/s, last-event age, dedup rate, reconnect
  count, rate-limit headroom.
- **Storage**: ClickHouse compaction lag, Postgres bloat, Redis hit
  ratio.

---

## 15. Reliability & SLOs

- **Availability**: 99.9 % monthly for the REST API; 99.5 % for live
  streams (an extra nine on REST because we can absorb feed gaps).
- **Tick freshness**: P95 ≤ 250 ms from source → UI WS during US market
  hours.
- **Snapshot latency**: P95 ≤ 100 ms.
- **Recovery time objective**: < 5 minutes from a node loss; warm-spare
  edge replicas accept traffic instantly via L4 health checks.
- **Recovery point objective**: 0 minutes for ClickHouse (replicated),
  0 minutes for Postgres (sync streaming replication to a hot standby),
  < 1 hour for object storage (cross-region replication async).
- **Source degradation policy**: if a connector is `Degraded`, edge
  responses include `X-Source-State: degraded` and the UI's status pill
  shows it red.

---

## 16. Deployment topology

**v1** (one region, two AZs):

- 1 NATS JetStream cluster, 3 nodes, 2-replica streams.
- 3× `termd-edge` behind a TCP load balancer with sticky sessions
  (consistent-hash on user-id cookie for cache locality).
- 1 each of `termd-ingest-eq`, `termd-ingest-crypto`,
  `termd-ingest-news`, `termd-ingest-fed`, `termd-ingest-edgar`,
  `termd-ingest-pmkt`, `termd-ingest-calendar`, `termd-ingest-rss` —
  these are mostly idle, single-binary, restartable.
- 1 ClickHouse node (32 vCPU / 128 GiB / NVMe), nightly snapshot to R2.
- 1 Postgres primary + 1 standby (16 vCPU / 64 GiB).
- 1 Redis (16 GiB).
- 1 Tantivy node (it's just a file-backed search index — packaged
  inside `termd-edge` and synced from S3).

**v2** scaling triggers:

- WS > 100 k concurrent → horizontal-scale `termd-edge`.
- Tick volume > 500 k msg/s → shard NATS by subject prefix.
- ClickHouse CPU > 60 % p99 → add a node (replicated MergeTree).

All packaged as static `musl` Rust binaries in Distroless containers,
≤ 30 MB each, started by Nomad in v1 (simpler than k8s for our scale).
k8s manifests in `deploy/k8s/` for v2.

---

## 17. Code quality — pedantic clippy + rustfmt

The point of this section is that *every* crate has the same lints
on, no exceptions hidden in lib.rs. The reviewer should be able to
rely on the linter, not on memory.

### 17.1 Workspace-level config

**`Cargo.toml` (workspace):**

```toml
[workspace.lints.rust]
unsafe_code = "forbid"
missing_docs = "warn"
missing_debug_implementations = "warn"
nonstandard_style = "deny"
rust_2018_idioms = "deny"
unreachable_pub = "warn"
unused_must_use = "deny"
unused_lifetimes = "deny"
unused_qualifications = "warn"
trivial_casts = "warn"
trivial_numeric_casts = "warn"

[workspace.lints.clippy]
all = { level = "deny", priority = -1 }
pedantic = { level = "deny", priority = -1 }
nursery = { level = "warn", priority = -1 }
cargo = { level = "warn", priority = -1 }

# Specific rules we want to *enforce* on top of pedantic:
unwrap_used = "deny"
expect_used = "warn"
panic = "warn"
todo = "warn"
dbg_macro = "deny"
print_stdout = "deny"
print_stderr = "deny"
indexing_slicing = "warn"
allow_attributes_without_reason = "deny"
arithmetic_side_effects = "warn"
as_conversions = "warn"
clone_on_ref_ptr = "warn"
exhaustive_enums = "warn"
exhaustive_structs = "warn"
float_arithmetic = "allow"        # we do plenty
float_cmp = "warn"
mem_forget = "deny"
missing_const_for_fn = "warn"
missing_errors_doc = "warn"
missing_panics_doc = "warn"
needless_pass_by_value = "warn"
shadow_unrelated = "warn"
str_to_string = "warn"
string_to_string = "warn"
unreadable_literal = "warn"
verbose_file_reads = "warn"

# Carve-outs (with reason):
module_name_repetitions = { level = "allow", priority = 1 }
must_use_candidate = { level = "allow", priority = 1 }
missing_errors_doc = { level = "allow", priority = 1 }   # too noisy in practice
similar_names = { level = "allow", priority = 1 }
```

Each crate's `Cargo.toml`:

```toml
[lints]
workspace = true
```

**Allowing a lint requires `#[expect(clippy::xxx, reason = "...")]`** —
the `allow_attributes_without_reason` rule above turns this from
gentleman's agreement into a compile error.

### 17.2 `rustfmt.toml`

```toml
edition = "2021"
max_width = 100
tab_spaces = 4
hard_tabs = false
newline_style = "Unix"
use_small_heuristics = "Max"
imports_granularity = "Crate"
group_imports = "StdExternalCrate"
reorder_imports = true
reorder_modules = true
match_arm_blocks = false
match_block_trailing_comma = true
overflow_delimited_expr = true
unstable_features = true
format_strings = true
format_macro_matchers = true
condense_wildcard_suffixes = true
```

### 17.3 `clippy.toml`

```toml
avoid-breaking-exported-api = false
cognitive-complexity-threshold = 25
type-complexity-threshold = 250
too-many-arguments-threshold = 7
too-many-lines-threshold = 200
trivial-copy-size-limit = 16
single-char-binding-names-threshold = 3
disallowed-methods = [
    { path = "std::env::var", reason = "use config::EnvConfig instead" },
    { path = "tokio::time::sleep", reason = "prefer `tokio::time::sleep_until` with deadlines" },
    { path = "std::process::exit", reason = "return errors; let main() decide" },
]
disallowed-types = [
    { path = "std::collections::HashMap", reason = "use ahash::AHashMap or hashbrown::HashMap" },
    { path = "std::sync::Mutex", reason = "use parking_lot::Mutex or tokio::sync::Mutex" },
]
```

### 17.4 CI

Every PR runs:

```yaml
- cargo +nightly fmt --all -- --check
- cargo clippy --workspace --all-targets --all-features -- -D warnings
- cargo nextest run --workspace --all-features
- cargo deny check
- cargo audit
- cargo machete                     # unused deps
- cargo +nightly udeps              # unused deps (orthogonal check)
- typos                             # spell check
- cargo doc --workspace --no-deps --document-private-items
```

CI fails on warnings — `-D warnings` makes them errors. Local
`pre-commit` hook runs `cargo fmt && cargo clippy --fix --allow-dirty`.

### 17.5 Dependency hygiene

- `cargo-deny` enforces our whitelisted licences (MIT, Apache-2.0, BSD-3,
  ISC, Unlicense, MPL-2.0).
- All deps pinned to exact versions in workspace `Cargo.toml`; no `*`.
- `cargo-audit` runs on every CI build.
- A dependency PR requires a brief justification in the PR body — it's
  not enforced by tooling, but we ask for it in the PR template.

### 17.6 Sanity tests every crate ships

- **Property tests** via `proptest` for any parser (Atom feeds, XBRL,
  CSV macro releases).
- **Round-trip tests** for every event variant: `event → MessagePack
  bytes → event` must round-trip.
- **Golden snapshot tests** for normalisers: `tests/golden/<source>/<n>.json`
  holds a real wire frame, the test asserts the canonical event.
- **Replay harness**: `termd-cli replay --tape tests/tapes/finnhub-monday-open.bin`
  rehydrates a full session — used to regression-test latency claims.

---

## 18. Performance targets

| Surface | Metric | Target |
|---|---|---|
| Tick fan-out | Server-side P99 | ≤ 1 ms |
| Tick end-to-end | Source recv → client recv P95 | ≤ 250 ms |
| Quote snapshot REST | P99 | ≤ 10 ms (L1 hit) |
| Chart 1m bars 1d REST | P99 | ≤ 30 ms (ClickHouse) |
| News search | P95 | ≤ 50 ms (Tantivy) |
| Filing fetch | P99 (cached) | ≤ 100 ms |
| Filing fetch | P99 (cold from S3) | ≤ 500 ms |
| WS connection setup | P99 | ≤ 100 ms incl. auth |
| Edge memory per WS | Median | ≤ 64 KB |
| Edge memory per WS | P99 | ≤ 256 KB |

Allocation budget on the hot path:

- 0 allocations to receive a NATS message and fan it out to N WS
  writers (everything is `Arc<Bytes>` / `Arc<str>`).
- 1 allocation for the wire frame on subscribe (`snapshot` only).
- 0 allocations on `delta` writes — they're prepared once on the
  publish side.

Achieved via:

- Object pools (`crossbeam-deque`) for `Vec<DepthLevel>` rebuilds.
- `Bytes` + `BytesMut` for all wire payloads.
- `smol_str::SmolStr` for symbol identifiers.
- `serde` with `#[serde(borrow)]` everywhere parsing borrows can be made.

---

## 19. Phased rollout

Each phase is independently shippable and produces a UI win.

Each phase has explicit *acceptance criteria* — until they're green,
the next phase doesn't start. CI gates the criteria via integration
tests in `crates/termd-test/`.

**Phase 0 — bootstrap (1 week)**

- Workspace scaffolding, CI, clippy config.
- `termd-core`, `termd-bus`, `termd-store` skeletons.
- `termd-edge` answers `/quote` from L1 (preloaded with mock data).

*Accepts when:* `cargo clippy -D warnings`, `cargo nextest run`,
`cargo deny check` all green in CI. `GET /api/v1/quote/NVDA` returns
a mock `Quote` with `Content-Type: application/json` in < 10 ms P99.

**Phase 1 — real equities + crypto (2 weeks)**

- `termd-ingest-eq` (Finnhub WS + REST candles).
- `termd-ingest-crypto` (Binance WS + REST).
- `termd-edge` streaming WS with subscribe / snapshot / delta.
- ClickHouse ticks/bars tables, basic Grafana dashboards.

*Accepts when:* P95 tick latency from Finnhub trade → client receive
≤ 250 ms during US market hours over a 1-hour replay; Binance L2
book applies 1 000 consecutive deltas across an artificial gap
without resync errors (tested with the `termd-test` replay harness);
chart endpoints return for every symbol in the watchlist in < 30 ms
P99.

**Phase 2 — macro + news (1 week)**

- `termd-ingest-fed` (FRED, BLS, BEA, ONS, Eurostat, e-Stat).
- `termd-ingest-news` (Finnhub + Reuters/AP RSS + GDELT).
- Postgres `news_index` + Tantivy index for headline search.

*Accepts when:* FRED `DGS10` updates appear in the API within 5
minutes of FRED publishing; news headlines from the last 24 h are
searchable in < 100 ms P95 over the Tantivy index; sentiment field
is populated on ≥ 70 % of items.

**Phase 3 — SEC EDGAR + calendars (2 weeks)**

- `termd-ingest-edgar` live + backfill.
- `termd-xbrl` extractor + `filing_facts`.
- `termd-ingest-calendar` (earnings + econ).
- New `CN` panel in UI for filings.

*Accepts when:* ≥ 99 % of new filings appear in the API within
60 s of EDGAR's atom feed listing them; XBRL extracts `us-gaap:Revenues`,
`us-gaap:NetIncomeLoss`, and `us-gaap:EarningsPerShareDiluted` correctly
for the top-100 SPX names (manual ground-truth sample).

**Phase 4 — prediction markets (1 week)**

- `termd-ingest-pmkt` (Polymarket + Kalshi).
- New `PMKT` panel in UI.

*Accepts when:* the top 20 markets on each venue stream without
disconnect for 4 hours; P95 quote latency < 500 ms.

**Phase 5 — user RSS + custom dashboards (1 week)**

- `termd-ingest-rss` (per-user feeds).
- User-feed configuration UI.

*Accepts when:* a user can `POST` an RSS URL and see items within
the configured cadence (default 5 min); auto-tagging recall on a
labeled set ≥ 0.9 for direct ticker mentions.

**Phase 6 — polish + extras (ongoing)**

- EIA, USDA, NOAA, Reddit, Stocktwits, FINRA, halts, IPO calendar.
- Tradier sandbox for options.
- Sentiment scoring on news via a small FinBERT distillation.

*Accepts when:* sentiment model ROC-AUC ≥ 0.8 on the labeled
financial-news corpus from `termd-test/data/sentiment-labels.csv`.

---

## 20. Symbol & identifier universe

The same instrument is known by many identifiers. A US-listed equity is
a ticker on Finnhub, a CIK at the SEC, a CUSIP in custody systems, an
ISIN to a European broker, and a FIGI to OpenFIGI. The backend
maintains a canonical `Symbol` and a bidirectional alias index so the
pipeline never has to ask *"what's the same thing?"* twice.

### 20.1 Canonical `SymbolRef`

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SymbolRef {
    pub canonical: SmolStr,       // BBRG-internal id, e.g. "NVDA"
    pub class: AssetClass,
    pub primary_venue: Mic,       // ISO 10383 — "XNAS", "XNYS", "BNCE", "POLY"
    pub display: SmolStr,         // human label, e.g. "NVIDIA CORP"
    pub aliases: Aliases,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AssetClass {
    Equity, Etf, Index,
    Fx, Crypto,
    FutureOutright, FutureSpread,
    OptionOutright,
    Bond, Cds, Curve,
    Macro, PredictionMarket,
    Custom,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Aliases {
    pub cik:     Option<u64>,         // SEC entity id
    pub cusip:   Option<SmolStr>,
    pub isin:    Option<SmolStr>,
    pub figi:    Option<SmolStr>,
    pub ric:     Option<SmolStr>,     // Refinitiv
    pub bbg:     Option<SmolStr>,     // Bloomberg
    pub finnhub: Option<SmolStr>,
    pub binance: Option<SmolStr>,
    pub poly_id: Option<SmolStr>,     // Polymarket condition id
    pub kalshi_ticker: Option<SmolStr>,
}
```

`Mic` is a tiny newtype around `SmolStr` constrained to four uppercase
letters at construction time.

### 20.2 `SymbolStore`

```rust
pub trait SymbolStore: Send + Sync {
    fn resolve(&self, canonical: &str) -> Option<Arc<SymbolRef>>;
    fn resolve_alias(&self, kind: AliasKind, value: &str) -> Option<Arc<SymbolRef>>;
    fn list_class(&self, class: AssetClass) -> Vec<Arc<SymbolRef>>;
    fn prefix_search(&self, prefix: &str, limit: usize) -> Vec<Arc<SymbolRef>>;
}

pub enum AliasKind { Cik, Cusip, Isin, Figi, Finnhub, Binance, PolyId, KalshiTicker, /* … */ }
```

Implementation:

* On boot, a hydrator merges three sources:
  * SEC's `company_tickers.json` and `company_tickers_exchange.json`
    (CIK ↔ ticker ↔ exchange for US listings — refreshed daily).
  * OpenFIGI bulk download (`https://api.openfigi.com/v3/mapping`)
    for CUSIP / ISIN / FIGI cross-reference.
  * Per-venue listings: Binance `/api/v3/exchangeInfo`, Polymarket
    `/markets`, Kalshi `/events`, Coinbase `/products`.
* Merged catalog persists to Postgres (`symbols` table partitioned by
  asset class) and a Tantivy prefix index for `prefix_search`.
* In-process cache: a sharded `DashMap<Cow<'static, str>, Arc<SymbolRef>>`
  keyed by every known alias; reads are lock-free, lookups <100 ns.
* Refreshed on a per-source cadence: SEC nightly, OpenFIGI weekly,
  Binance every 10 minutes (listings change intraday).
* Connectors call `resolve_alias(kind, raw)` before emitting any event
  carrying that symbol. Unknown identifiers buffer for 60 s in a
  `pending_resolve` queue and re-try once before emitting a
  `Status { code: "UNKNOWN_SYMBOL", message: <raw> }` and dropping the
  parent event.
* The UI's command palette uses `prefix_search` over the WS subprotocol
  for instant-fill behaviour (the Tantivy reader sits inside `termd-edge`
  via an mmap'd index file synced from object storage).

### 20.3 Special cases

* **Futures** (CL1, CO1, etc.): synthesized roots, mapped to the active
  front-month contract by a separate `RollSchedule` table. Connector
  output is a `Tick` with `symbol = "CL1"`; downstream consumers can
  resolve through the roll table to the concrete CME contract for
  audit.
* **Options**: encoded with the OCC 21-character format
  (`NVDA  260620C00150000`). The UI displays prettily; the canonical
  form keeps OCC.
* **Crypto cross-venue**: BTCUSDT on Binance and BTC-USD on Coinbase
  resolve to the same canonical `BTCUSDT Crypto`; per-venue last is
  tracked separately in L1.

---

## 21. Time, market hours, holidays

### 21.1 UTC discipline

Every timestamp in canonical events is **UTC**. The only places local
time appears:

* UI string formatting (top-bar clock in ET).
* Econ-calendar event display ("08:30 NY time").
* Market-session decisions (NYSE 09:30-16:00 ET — converted on demand).

Connectors that receive timestamps in venue-local time convert to UTC
at the parsing boundary, never later. `time-tz` provides the
IANA-database-backed conversions; the IANA tzdata is bundled into the
binary via `tzdb` so deployments don't depend on the OS database.

### 21.2 `MarketSession` module

```rust
pub trait MarketSession: Send + Sync {
    fn state(&self, exchange: Mic, at: OffsetDateTime) -> SessionState;
    fn next_open(&self, exchange: Mic, after: OffsetDateTime) -> OffsetDateTime;
    fn next_close(&self, exchange: Mic, after: OffsetDateTime) -> OffsetDateTime;
    fn is_trading_day(&self, exchange: Mic, date: time::Date) -> bool;
    fn is_half_day(&self, exchange: Mic, date: time::Date) -> bool;
}

pub enum SessionState { Pre, Open, Lunch, Close, Post, Closed, Holiday }
```

Schedules per exchange live in
`termd-core/src/sessions/<mic>.toml` — a small declarative file:

```toml
[XNAS]                          # NASDAQ
timezone = "America/New_York"
regular   = "09:30..=16:00"
pre       = "04:00..<09:30"
post      = "16:00..<20:00"
half_day  = "09:30..=13:00"
holidays_2026 = [
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
  "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
  "2026-11-26", "2026-12-25",
]
half_days_2026 = ["2026-11-27", "2026-12-24"]
```

Refreshed annually from each venue's published calendar. Schedules
shipped a year ahead; CI fails if the next year's table is missing
within 60 days of year-end.

### 21.3 Use by connectors

* Equity connectors throttle to 1 poll per minute during `Closed`,
  back up to documented cadence inside `Open` / `Pre` / `Post`.
* The chart endpoint uses `MarketSession::state` to decide whether to
  serve "current session intraday" or "last close + post-market"
  ranges by default.
* The status-bar pill in the UI is driven directly by per-venue
  `state` — no client-side guessing.

### 21.4 Daylight saving correctness

A test suite (`termd-test/src/dst.rs`) asserts:

* NYSE 09:30 ET is `13:30Z` on a winter day, `13:30Z` on a summer day
  also (because ET shifts but UTC is fixed for the same clock-time
  expression — yes really).
* London 16:30 GMT is `16:30Z` in winter, `15:30Z` in summer.
* No event has `src_ts > ingest_ts + 5s` (would indicate a TZ misparse).

---

## 22. Schema evolution & wire compatibility

Three flavours of compatibility, each handled differently:

### 22.1 Internal NATS wire (ingest ↔ edge)

* Full control over both producers and consumers, deployed together.
* We can ship breaking changes freely; CI gates each release with a
  `termd-test::compat_internal` step that loads a corpus of recorded
  events from `tests/golden/wire/*.msgpack` and asserts they
  round-trip through both old and new decoders.

### 22.2 WebSocket protocol (edge ↔ SPA)

* Semver-style. `Sec-WebSocket-Protocol: bbrg.v1` (see §11.1).
* `bbrg.v2` ships when we have a breaking change; `bbrg.v1` continues
  to serve for at least one minor release after `v2` is GA. A
  `Deprecation: true` header on REST and a `warning` frame on WS tell
  clients to upgrade.
* Additive changes (new event variant, new optional field) live within
  the existing version — clients must tolerate unknown variants by
  ignoring them.

### 22.3 REST API

* URI-versioned: `/api/v1/...`. Bumping introduces `/api/v2/...`
  in parallel. Sunset window: one minor release.
* OpenAPI spec is the source of truth; CI fails if a handler's request
  or response type changes without bumping a `version` annotation in
  the `utoipa` derive.

### 22.4 Database migrations

* Postgres: `refinery` migrations in `crates/termd-store/migrations/`
  applied on every deploy with an advisory lock. Rollback scripts in
  the same directory.
* ClickHouse: SQL migrations applied via `clickhouse-rs` at boot. We
  forbid destructive migrations (DROP, TRUNCATE) in tooling; they
  require a manual flag.
* Tantivy: index format is forward-incompatible per its docs. On a
  Tantivy bump, the connector rebuilds the index from canonical store
  before the new edge takes traffic.

### 22.5 Why MessagePack

We chose `rmp-serde` (MessagePack) over the alternatives:

| Format | Why not (for our case) |
|---|---|
| Protobuf | Needs `.proto` files; doubles the schema source of truth. |
| Flatbuffers | Faster encode/decode but the IDL friction outweighs it at our payload size. |
| Cap'n Proto | Same IDL friction; zero-copy story doesn't help when we MessagePack-encode anyway. |
| SBE | Bespoke for FIX-like binary. Overkill. |
| JSON | Human-readable wins but 3× the bytes per frame. We use JSON only at the REST surface. |

MessagePack with the same `serde` derives as our REST/SQL paths gives
us one schema source-of-truth, an ~150 B per-tick payload, and a
decode time within 10 % of a hand-tuned binary format.

---

## 23. Data quality, dedup, reconciliation

Bad data is the default assumption. Five layers of defence, in order
of cost:

### 23.1 Per-source dedup window

Every connector keeps a 5-minute ring of seen `(source, id)` pairs (or
content-hash when no id is available). Hits drop silently before any
publish. Implemented as a `tinyset::SetU64` of FxHashed identifiers
behind a `Mutex` shared across the connector's parser tasks.

### 23.2 Sequence-number ordering

For ordered streams (L2 books especially):

* Binance: `U..u` window must satisfy `U <= last_update_id + 1 <= u`;
  out-of-order increments trigger a snapshot resync.
* Polymarket / Kalshi: each frame carries a monotonic seq; gaps
  trigger a fresh `book` snapshot subscription.
* Finnhub trades: re-emission within the dedup window is dropped; out
  of order trades by timestamp are tolerated (exchange already serial
  per venue).

### 23.3 Schema validation

Connectors must not emit invalid events. `validate()` runs in `cfg(test)`
and behind `debug_assertions` in `cfg(debug_assertions)` builds — zero
cost in release. CI runs a `tests/corpus_replay.rs` over a corpus of
hand-curated bad frames and asserts each connector's `validate` rejects
them.

Examples of invariants enforced:

* `Tick.px > 0.0 && !px.is_nan()`
* `Quote.bid <= Quote.ask`
* `DepthLevel.qty >= 0.0`
* `EconEvent.importance in 1..=3`
* `Filing.form` is in a known set; unknown forms emit a structured
  warning to a dead-letter subject for triage rather than land in
  canonical store.

### 23.4 Cross-source reconciliation

Where two independent feeds give us the same metric (Finnhub +
Tiingo for US equity last, FRED + BIS for policy rates), the edge keeps
`latest_by_source` and computes a `discrepancy_score`:

* Pricewise: `|primary - secondary| / mid > 0.005 (50 bps)` for > 30 s.
* Headline-news: same article identified by Jaccard similarity > 0.85
  across providers within 60 s of each other.

Discrepancies emit a `quality.discrepancy` event with both values and
provenance; a Prometheus counter increments. Soft alert if > 10/min
across the whole platform.

### 23.5 Replay-vs-realtime daily check

At 02:00 ET we replay the prior session from ClickHouse (`SELECT … WHERE
ts >= yesterday`) and recompute the snapshots we served live (close-of-day
quote, daily bar, end-of-day greeks). Diffs land in
`tests/regressions/<date>.json` and gate the next-day deploy until
investigated.

### 23.6 Dead-letter pattern

Anything that fails dedup, validation, or reconciliation lands on
`dlq.<source>.<reason>` with the original payload plus parse context.
DLQ messages are retained 7 days and inspected through `termd-cli dlq`.

---

## 24. Connector control plane

`termd-cli` is the admin tool. Each ingest binary exposes a small
JSON-over-HTTP control surface on a privileged port (default `:7300`,
bound to the deployment network), and the CLI calls into it:

```
termd-cli status                          # all connectors, freshness, error rate
termd-cli status edgar --verbose          # one connector deep-dive
termd-cli pause edgar                     # stop emitting; clean reconnect on resume
termd-cli resume edgar
termd-cli reconnect finnhub               # force a fresh WS upstream
termd-cli replay edgar --from 2026-05-01 \
    --to 2026-05-07 --to-subject scratch  # re-emit historicals onto a side subject
termd-cli backfill bls --series LNS14000000 \
    --from 2010-01-01
termd-cli reindex search --target news    # rebuild Tantivy from canonical store
termd-cli dump symbol NVDA                # everything we know about a symbol
termd-cli dlq list edgar --since 1h
termd-cli dlq replay edgar <message-id>   # re-enqueue a DLQ'd payload after fix
termd-cli quota show --user 42
termd-cli quota set --user 42 --tier pro
termd-cli flag set msft_dark_pool true    # feature flags via Redis
```

Auth via **mTLS**: the CLI carries a deploy-only certificate; the
control-surface server validates the cert against an internal CA.
No password, no API key — these endpoints don't see human auth.

`termd-cli` is itself shipped as a static musl binary in a tiny
Distroless container so operators can `docker run --rm bbrg/termd-cli`
without a Rust toolchain.

---

## 25. Idempotency & exactly-once writes

REST mutating endpoints (`POST /orders`, `POST /alerts`,
`POST /users/me/rss`, `DELETE /alerts/{id}`) accept an
`Idempotency-Key` header. Behaviour:

* Server hashes the key + request body and stores `(hash → response)`
  in Redis for 24 h.
* A repeated request with the same key and body returns the original
  response with status 200 (or 201, but the body is preserved
  verbatim). The original `Location` header survives.
* A repeated key with a *different* body returns 422 with a
  problem-document explaining the conflict. We don't allow silent
  override.

The simulated OMS uses this to guarantee one-fill-per-button-click
under aggressive client retry — the UI sends `Idempotency-Key:
<uuid-v7>` derived from the user's click event.

For internal writes (ingest → ClickHouse), idempotency is structural:
* ClickHouse `ReplacingMergeTree` on `(symbol, ts)` for ticks de-dups
  on merge.
* Postgres tables with natural primary keys (`accession`, `news_id`,
  `filing_id`) use `INSERT … ON CONFLICT DO UPDATE` with explicit
  conflict targets; no upserts are silent.

---

## 26. Local development & secrets

### 26.1 docker-compose

```yaml
# docker-compose.dev.yml (excerpt)
services:
  nats:       { image: nats:2-alpine, command: -js }
  clickhouse: { image: clickhouse/clickhouse-server:24-alpine }
  postgres:   { image: postgres:16-alpine, environment: { POSTGRES_PASSWORD: dev } }
  redis:      { image: redis:7-alpine }
  minio:      { image: minio/minio, command: server /data }
  grafana:    { image: grafana/grafana-oss:11 }
  loki:       { image: grafana/loki:3 }
  tempo:      { image: grafana/tempo:2 }
  vector:     { image: timberio/vector:0.40-alpine }
```

`make dev` brings everything up. `make seed-mock` publishes a
deterministic synthetic stream on NATS so the UI renders even before
any provider API keys are configured. `make seed-edgar` backfills 30
days of EDGAR filings so the `CN` panel has content.

### 26.2 Toolchain

* `rust-toolchain.toml` pins to `stable 1.81+`.
* `Justfile` (or `Makefile`) targets: `dev`, `fmt`, `lint`, `test`,
  `bench`, `seed-mock`, `tail` (live log).
* Optional `flake.nix` for `nix develop` reproducible env — Rust,
  clippy, rustfmt, sqlx-cli, cargo-nextest, mold linker, watchexec,
  dasel.
* `mold` linker for ~3× link-time speed-up on Linux dev hosts.

### 26.3 Secret management

Three places config is read from, in order of precedence:

1. CLI flags — one-off overrides.
2. Environment variables — `TERMD_FINNHUB_KEY`, `TERMD_FRED_KEY`, etc.
3. A file pointed to by `TERMD_CONFIG_PATH` (TOML).

No secret lives in source. CI runs `gitleaks` on every PR. Production
secrets sit in **AWS Secrets Manager** (or HashiCorp Vault for
self-hosted), pulled at boot via a sidecar secrets-injector that
writes to a tmpfs read by the process. Rotation is a SIGHUP-driven
reload — no restart.

API keys for user-pasted upstream services (e.g. a personal Polygon
key) are encrypted at rest with a per-user envelope key derived from
the user's password + a server-side master via Argon2id.

---

## 27. Cost estimates

Approximate monthly running cost at v1 scale (≈ 10 k DAU, ≈ 2 k
concurrent WS, US equity + crypto + macro + EDGAR). USD.

| Line item | Provider / shape | Cost |
|---|---|---|
| Compute — 3× edge (8 vCPU / 16 GiB each) | Hetzner CCX33 | ~$120 |
| Compute — 8 ingest binaries (avg 2 vCPU / 4 GiB) | Hetzner CCX13 | ~$80 |
| ClickHouse (32 vCPU / 128 GiB / 1 TB NVMe) | Hetzner CCX63 + NVMe | ~$220 |
| Postgres primary + standby (16 vCPU / 64 GiB) | Hetzner / managed | ~$160 |
| Redis (16 GiB managed) | Upstash / Fly.io | ~$60 |
| Object storage (R2, ~500 GB filings + snapshots) | Cloudflare R2 | ~$8 (no egress) |
| NATS JetStream cluster (3 nodes) | Hetzner | ~$45 |
| Egress (≈ 5 TB/mo at 250 MB/s peak) | Hetzner egress included | $0 |
| Finnhub free tier | Finnhub | $0 |
| Tiingo free tier | Tiingo | $0 |
| Twelve Data free tier | Twelve Data | $0 |
| FRED, BLS, BEA, ONS, Eurostat, e-Stat | Government agencies | $0 |
| OpenFIGI | OpenFIGI | $0 (within rate limit) |
| SEC EDGAR | SEC | $0 |
| Polymarket + Kalshi (read-only public APIs) | Each | $0 |
| Monitoring (Grafana Cloud free or self-hosted LGTM) | Grafana Cloud | $0 |
| **Estimated total** | | **~$700 / month** |

Natural paid upgrades when the free tiers stop being enough:

* Finnhub paid plan ($60–$250 / month) — real-time US quotes + larger
  symbol cap.
* Polygon Starter ($30 / month) — delayed-15-min options chains.
* OpenAI / Anthropic API for sentiment if local FinBERT under-performs.

None of these require architectural changes — they all swap in behind
the existing connector traits.

---

## 28. Backup, restore, graceful shutdown

### 28.1 Error budget & on-call

99.9 % monthly REST availability ⇒ **43 m 12 s** budget per calendar
month. The SRE rotation tracks:

* Burn rate (alert at < 50 % remaining with > 50 % of month left).
* Per-source uptime, with named owners.
* MTTD / MTTA / MTTR from PagerDuty exports.
* Two pages / month is the cap before we declare an incident review
  and freeze feature releases.

### 28.2 Backup procedures

* **Postgres** — continuous WAL streaming to a sync standby; daily
  `pg_basebackup` to R2 (AES-256 client-side encrypted); PITR window =
  14 days; restore drill quarterly with RTO 30 min, RPO 0.
* **ClickHouse** — replicated `MergeTree` factor 2; nightly `BACKUP
  TABLE … TO Disk('r2', 'YYYY-MM-DD/')`; restore via `RESTORE TABLE`
  from the most recent valid snapshot.
* **Tantivy** — rebuilt from canonical store on demand
  (`termd-cli reindex`); not separately backed up.
* **Object storage (R2)** — versioning enabled, 90-day retention,
  nightly cross-region replication to a second bucket.
* **NATS JetStream** — replicated 2× within the cluster. Stream loss
  is non-fatal because the canonical store is replayable.

### 28.3 Restore drill

A quarterly game-day:

1. Spin up a parallel "DR" stack in a different AZ from a clean state.
2. Apply the most recent Postgres `pg_basebackup`.
3. Restore ClickHouse from the latest `BACKUP`.
4. Hydrate Tantivy via `termd-cli reindex search --all`.
5. Point a synthetic client at the DR edge; verify quotes / news /
   filings within 30 minutes.
6. Tear down. Record any procedure friction in `runbooks/restore.md`.

### 28.4 Graceful shutdown

On SIGTERM, every process:

1. Removes itself from the L4 load-balancer pool by failing `/readyz`.
2. Stops accepting new work — Axum stops binding; NATS subscribers
   unsubscribe with their current subjects.
3. Drains in-flight requests with a **30-second** deadline.
4. Sends each open WS connection a `close` frame with code **1012**
   ("Service Restart") and a 200-byte JSON body indicating the client
   should reconnect.
5. Flushes any buffered writes to ClickHouse / Postgres / Redis.
6. Exits 0.

A **60-second hard kill** follows SIGTERM if drain hasn't completed,
to keep deploys bounded.

### 28.5 Disaster recovery RTO/RPO summary

| Component | RTO | RPO |
|---|---|---|
| Postgres | 30 min | 0 (sync standby) |
| ClickHouse | 60 min | 5 min |
| Tantivy | 4 hours (rebuild) | n/a |
| R2 | <5 min (versioned bucket) | <1 hour cross-region |
| NATS JetStream | 5 min | 0 (replicated) |
| Whole-region loss | 4 hours | 1 hour |

---

## 29. Open questions

Items that are *actually* unresolved, with current best guesses where
applicable. Items that I'd documented as open in earlier drafts and
have since landed in this document are marked **(resolved)** with a
pointer to where.

1. **(resolved)** WS protocol versioning — see §11.1; `bbrg.v1`
   subprotocol header from day one.
2. **(resolved)** Kalshi cert auth in-browser — confirmed: backend
   holds the cert, UI talks only to our WS. §7.7.
3. **(resolved)** Idempotency on writes — `Idempotency-Key` with
   24 h Redis TTL. §25.
4. **(resolved)** Symbol identifier resolution — `SymbolStore` over
   SEC tickers + OpenFIGI + per-venue listings, daily refresh. §20.
5. **Latency vs. cost on EDGAR** — current plan polls every 15 s
   during market hours. EDGAR's atom feed updates in 1-minute batches
   so finer polling is wasted effort. **Decision: stay at 15 s** unless
   we observe end-to-end miss-windows > 60 s in production.
6. **Options chain freshness on free tier** — Yahoo unofficial is
   best-effort; Tradier sandbox is rate-limited but reliable. **Tentative
   plan: ship Tradier in phase 6**, keep mock for OVDV until then.
7. **Sentiment provider** — local FinBERT distilled to a < 50 MB ONNX
   vs. external API. **Lean local** (privacy + cost stability), but
   keep a fallback adapter for OpenAI-style scoring if quality is
   inadequate on labeled set.
8. **Polymarket on-chain fallback** — worth implementing in v1, or wait
   for CLOB API to demonstrably miss state? **Wait** unless we see
   resolution-event drift > 5 min during the v1 phase 4 acceptance run.
9. **Backup equity provider** — Finnhub is a single point of failure.
   **Plan: warm-standby Tiingo** with switchover within 30 s of Finnhub
   heartbeat loss. Adds ~2 weeks to phase 1 deliverable; pending
   prioritisation.
10. **GDPR + custom RSS** — users submit URLs that may contain personal
    data in headlines. **Plan: privacy policy + per-feed export/delete
    endpoints** before user RSS leaves staging.
11. **Multi-region** — single region in v1 (London / FRA). Cross-region
    active-active with NATS leaf nodes is feasible but not justified
    until > 100 k concurrent users. Open: which region pairing
    minimises p99 latency for the largest user cohort (likely
    NYC + LON).
12. **Symbol universe quality** — OpenFIGI's free tier rate-limits
    aggressive bulk download. Open: whether to maintain our own
    cross-reference table from EDGAR + Binance + Polymarket directly,
    falling back to OpenFIGI only for less common identifiers.
13. **Compliance for simulated OMS** — even though our orders never
    route to a venue, do we still need to retain audit logs at the
    same standard as a real OMS? Probably not, but the lawyer's
    answer is pending.

---

*Last updated: 2026-05-14. Owner: termd backend team.*
