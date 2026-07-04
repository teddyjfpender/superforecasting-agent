# The Prediction-Market Data Plane

This is the internals of `forecasting/pm/` — Arc C's read-only window onto
Polymarket and Kalshi. It reads events, de-vigged outcome distributions, order
books, price history, and live streams; it never trades. The honesty guards that
govern every number here have their own page,
[estimator-honesty.md](estimator-honesty.md); this page is the *plumbing* — how
venues are fetched, normalized, ranked, cached, streamed, and surfaced.

The wire it exposes is the `pm.*` RPC family plus the `pm.tick` event (Arc A);
the agent reaches the same data through the `forecast_ledger` tool's `pm_query`
action ([architecture.md](../architecture.md) Arc C,
[reference/providers.md](../reference/providers.md)).

```
      pm.list / pm.detail / pm.book / pm.history / pm.stream.*   (protocol/rpc/pm.py)
                                 │
                          ┌──────▼───────┐
                          │  PMService   │  TTL cache + disk tape + rank-interleave
                          │  service.py  │
                          └──┬────────┬──┘
                 ┌───────────▼─┐    ┌─▼───────────┐        ┌──────────────┐
                 │ Polymarket  │    │   Kalshi    │        │  PMStreamHub │
                 │ Gamma+CLOB  │    │ REST + WS   │        │  stream.py   │
                 └──────┬──────┘    └──────┬──────┘        └──────┬───────┘
                        └──── PMEvent / PMMarket ───────┐         │
                                      │  build_distribution       │ pm.tick
                                      ▼  (aggregate.py)           ▼ (server estimate)
                                PMDistribution  ──────────▶  TUI Markets view
```

Everything is split **parse (pure) from fetch (I/O)** so the parsers run against
recorded fixtures and never touch the network; every client takes an injectable
`fetch`, and the service takes an injectable clock + spawn for deterministic
tests.

---

## Venue adapters

### Polymarket — Gamma discovery + CLOB pricing

`forecasting/pm/polymarket.py`. Public data only, no auth. Discovery is the Gamma
API (`/events` with nested `markets[]`, `/events/{id}`); pricing/history is CLOB
(`/book`, `/midpoint`, `/prices-history`). Quirks the parser absorbs:

- Gamma serialises arrays as **JSON strings** (`'["Yes","No"]'`) — `_json_list`
  parses via `json.loads` then `ast.literal_eval`.
- A **text query** hits Gamma's dedicated `/public-search` endpoint (full
  catalog), not a filter over the one top-volume page. The old page-filter
  behaviour silently missed everything below the fold — the operator: *"i cant
  seem to search through all markets"*. The search path **fails open** to the
  page filter if `/public-search` errors.
- `negRisk` / `enableNegRisk` sets `mutually_exclusive` — the flag the
  aggregator's earned-normalization check reads.

All fetches go through `forecasting/pm/_http.py` (`http_get_json`): a bounded
stdlib GET with a `_READ_CAP` (32 MiB) so a hostile response can't exhaust
memory, an env-tunable timeout, and a custom `hermes-pm/1.0` User-Agent. Any
network/HTTP/decode failure raises `PMHTTPError` so callers degrade politely.

### Kalshi — REST catalog + signed WS

`forecasting/pm/kalshi.py`. REST market data is **public** (the keyless
default); the RSA-PSS signer (`sign_kalshi_message`, `kalshi_auth_headers`) is
only for the authed websocket handshake, and `cryptography` is imported **lazily**
so the package works without it. Kalshi has **no text-search endpoint**, so
search is a bounded two-phase scan:

1. **Series phase.** Whole market *families* (e.g. the daily max-temperature
   series) sit thousands of events deep and never surface in an event scan.
   Matching the **series catalog** (title/ticker) reaches them directly — the
   operator's *"i can't see any max temperature markets"* bug. The catalog is
   cached for an hour (`_SERIES_CATALOG_TTL`, up to 2×200 rows); re-fetching it
   per keystroke-debounced query was the dominant search cost (measured
   seconds). `warm_catalog()` primes it out of band so the first `/` search never
   pays the cold ~1.8s scan.
2. **Cursor scan.** A bounded scan of open events (`_SEARCH_MAX_PAGES` × 200),
   reading **light pages** (titles only — nested market payloads were the
   dominant cost), filtered by title, then **hydrated in parallel**. When the
   series phase already found precise hits, the fuzzy net shrinks to 2 pages.

**The revived import-time crash.** `_series_catalog` calls `time.monotonic()`,
but the module had no top-level `import time` — so the *entire* series-search
phase raised `NameError` and was silently swallowed by the fail-open `except`.
The series phase looked implemented but was dead; adding the module-level import
revived it. `test_pm_kalshi.py::test_series_catalog_scans_and_caches_without_nameerror`
is the regression pin. (This is a recurring hazard of fail-open `try/except`:
a swallowed exception makes a broken feature indistinguishable from a working
one — the test asserts the scan *actually happens*.)

Both venues also normalize a Kalshi order book to a **YES view**: Kalshi quotes
both sides as bids, so a NO bid at price `p` becomes a YES ask at `1 - p`
(`parse_orderbook`).

---

## YES-orientation hierarchy

Every venue normalizes into the frozen `PMMarket`, and the derived
`PMMarket.yes_mid` is the honest YES probability. The precedence differs for open
vs closed markets, and getting it wrong is fabrication class #5 in
[estimator-honesty.md](estimator-honesty.md):

- **Open market:** prefer the two-sided quote mid (`honest_yes_mid`), then the
  YES-oriented `outcomePrices` (volume-gated), then the direction-ambiguous
  `lastTradePrice` as a last resort.
- **Closed (resolved) child:** the book is **voided** — `outcomePrices` holds the
  terminal truth (YES 0 or 1), and `lastTradePrice` is explicitly *not* trusted
  (it can be the NO-side redemption print).

---

## Aggregation — categorical families to headline + sub-rows

`forecasting/pm/aggregate.py` collapses a `PMEvent` into a `PMDistribution`: an
ordered set of de-vigged `PMOutcome` rows plus a synthesised **headline** (top
label + prob, `n`, total volume, close time). The contract the TUI renders is
*headline row + expandable sub-rows*.

Mechanics:

- **Duplicate collapse.** Venues carry dead duplicate outcome markets (two
  "Robert F. Kennedy Jr." rows — one live, one an untraded placeholder). The
  aggregator keeps the **most liquid market per label** so an outcome appears
  exactly once.
- **De-vig.** Multiplicative normalization over YES mids — divide each by the sum
  so a mutually-exclusive partition sums to ~1, reporting the removed overround
  honestly. Zero-liquidity outcomes get prob 0, are excluded from the
  normalising denominator, and rank last.
- **Earned normalization.** Only a `mutually_exclusive` event whose book sum sits
  in `[0.85, 1.25]` is normalized; otherwise raw prices are shown with a note and
  `normalized=False`. (The epistemic guard — see the honesty doc.)
- **Honest ordering + notes.** Rows rank by de-vigged prob (illiquid last, ties
  break on raw mid then volume), and `notes` narrate what happened ("some
  outcomes have no live quote", "removed +N pts of overround", "raw prices
  shown"). `raw_prob` sits alongside `prob` on every row for a raw-vs-devig audit.

Binary (single-market) events pass through untouched — no de-vig, `overround=0`.

---

## Ranking — rank-interleaved venue lanes

`PMService._load_events` ranks **within** each venue by volume (the honest
relevance proxy — raw API order surfaces whatever a venue promotes), then
**rank-interleaves across** venues rather than merging on a shared key. The reason
is load-tested: **raw volumes are not comparable across venues** — Polymarket
lifetime-dollar volume dwarfs Kalshi contract volume, so a naive volume-sorted
merge silently evicts Kalshi from the whole list. Interleaving keeps both venues
represented at every list prefix. Venues are fetched **in parallel** (serial
fetches doubled cold latency; a text query costs seconds per venue), and one
venue raising never blanks the tape (its lane becomes `[]`).

---

## Caching — in-memory TTL + disk tape

`PMService` runs a `TTLCache` with **stale-while-revalidate**: a stale hit returns
the old value immediately and refreshes out of band, so the desk never blocks on
a slow venue. TTLs: list 30s, detail 15s, history 5m. **Books are never cached**
— they move too fast.

On top of that is a **disk-persisted tape** (`{home}/pm_cache.json`, atomic
write, version-stamped, bounded to `_DISK_MAX_KEYS = 8`). On a cold gateway
start the in-memory cache is empty; rather than block the first paint on the
~0.6s live fetch, `list_events_payload` serves a persisted browse tape
**immediately** with `stale=True` and kicks off a single background revalidate.
Only **browse tapes** (no query/tag) are persisted — searches would go stale
wrong. The disk file is rewritten only on a real network **miss**, not on every
30s warm poll. Rows keep their **original honest estimates**; the stale flag is
the only UI-visible change (fabrication class #10). `prewarm()` fetches the
default tape and primes the Kalshi series catalog at gateway boot so even the
first-ever run pays the cold fetch off the request path.

---

## Streaming — one connection per venue, server-side estimate

`forecasting/pm/stream.py` (`PMStreamHub`) owns **one long-lived websocket per
venue** with subscriptions multiplexed onto it, auto-reconnect with bounded
exponential backoff, and the live subscription set re-sent on every reconnect.
The wire format is a separate pure module (`stream_wire.py`) so parsing is
unit-testable on its own.

- **Polite degradation.** No `websockets` lib, or no Kalshi key → `start` returns
  `{"streaming": False, "reason": ...}` and the desk falls back to REST polling.
  Nobody raises.
- **Fresh signatures.** The Kalshi handshake needs an RSA-PSS signature over
  `timestamp+GET+path`; the header factory is called **anew on every reconnect**
  so the timestamp never ages out (a static dict computed once at `start()`
  would be rejected on reconnect).
- **Server-computed `estimate`.** Each `Tick` carries the honest probability
  computed server-side via `honest_yes_mid`, `None` when the frame carries no
  estimate-grade information. The gateway re-emits it as `pm.tick`; consumers fold
  *only* this field (the proof-by-absence guard, honesty doc #9). Polymarket
  `price_change` frames are level deltas — no estimate is derivable and none is
  invented.

`invalidate_market` lets a tick evict the touched detail-cache entry so a live
move doesn't sit behind a 15s TTL.

---

## Price history

`forecasting/pm/history.py` normalizes both venues into `[{ts, p}]` and
downsamples with a uniform stride that always preserves the first and last point
(cheap sparklines, undistorted endpoints). `PMService` translates the desk's
single lookback vocabulary (`1d/1w/1m/all`) into each venue's native params in
one place — Polymarket's CLOB `interval` enum (mapping `all` → `max`) and
Kalshi's `candlesticks`, which *requires* a `start_ts + end_ts + period_interval`
window or returns HTTP 400.

---

## Deep search + discovered-pool persistence

Search is not just a filter — it **compounds the tape's coverage**. The TUI keeps
a session pool of events the operator surfaced via `/` deep search
(`ui-tui/src/lib/usePmDiscovered.ts`), persisted to `markets.json` (`pmSaved`)
as a **100-entry LRU** and re-hydrated via `pm.detail` on mount. Searches thus
*accumulate* — the operator: *"persist... so we maximally cover the markets"*.
Discovered rows are marked (a `+` gutter in `predictionMarketsTable.tsx`) and are
individually removable (a mis-search drops from both the pool and `pmSaved`).
Fan-out is fetched in small groups so a 100-item pool paints progressively
without 100 re-renders or bursting the gateway.

---

## Default filters

The Prediction section's out-of-the-box filter (`DEFAULT_PM_FILTER` in
`ui-tui/src/lib/pmRows.ts`) is **everything off except hide-dead**. A row is
*dead* when it has **no headline estimate** (top_prob is null), **zero volume**,
or is **past its close time** — the operator: *"don't spam the TUI with useless
rows"*. Crucially, "0%" is *not* dead: a real 0.85% market with volume (the RFK
case) is very much alive — dead means **no estimate at all**, which is exactly the
honest `None` the honesty doctrine produces. The `f` modal
(`pmFilterModal.tsx`) adds venue, topic, min-volume ($-shorthand), a prob range,
and an honestly-labelled "hide sports" heuristic. Prob bounds exclude any item
with no headline prob — a bound can't be met by a value that was never
fabricated.

---

## The `pm.*` RPC surface

`protocol/rpc/pm.py` (Arc A) defines the wire, transcribed faithfully from the
server's actual `to_dict` emission and cross-checked against the TUI DTOs — where
the two disagreed **the server won**, and the divergences are noted inline
(e.g. `total_volume` is always a number server-side, never null). The family:

| RPC | Purpose |
| --- | --- |
| `pm.list` | Ranked, interleaved browse/search tape (`[{event, distribution}]` + stale flag). |
| `pm.detail` | One event + its full distribution. |
| `pm.book` | A YES-oriented order book (always fresh). |
| `pm.history` | Downsampled `[{ts, p}]` price history. |
| `pm.stream.start` / `pm.stream.stop` | Subscribe/unsubscribe a venue's tick stream; `pm.tick` carries the server estimate. |

The exhaustive, generated request/response schema is in
[reference/protocol.md](../reference/protocol.md); the venue registry (base URLs,
aliases) is in [reference/providers.md](../reference/providers.md).

`forecasting/pm/health.py` folds a read-only PM section into `forecast doctor`:
streaming readiness (websocket lib present, Kalshi key present, `cryptography`
available) and cache counts — computed defensively so a probe failure never fails
the audit, and only touching the network when explicitly asked.

---

## Sources

Verified against the current tree (`superforecasting-agent-snapshot`):

- `forecasting/pm/polymarket.py`, `kalshi.py`, `_http.py` — venue adapters, search, signer.
- `forecasting/pm/aggregate.py` — `build_distribution`, de-vig, duplicate collapse, notes.
- `forecasting/pm/service.py` — `PMService`, TTLs, rank-interleave, disk tape, prewarm.
- `forecasting/pm/stream.py`, `stream_wire.py` — `PMStreamHub`, per-venue reconnect, `Tick.estimate`.
- `forecasting/pm/history.py`, `health.py` — downsample, doctor fold-in.
- `forecasting/pm/model.py` — the frozen `PMEvent`/`PMMarket`/`PMDistribution` shapes.
- `protocol/rpc/pm.py` — the `pm.*` wire models.
- `ui-tui/src/lib/usePmDiscovered.ts`, `pmRows.ts`, `pmData.ts`, `components/pmFilterModal.tsx`, `predictionMarketsTable.tsx` — discovered-pool LRU, default filters, "—" rendering.
- Tests: `tests/forecasting/test_pm_polymarket.py`, `test_pm_kalshi.py`, `test_pm_aggregate.py`, `test_pm_service.py`, `test_pm_stream.py`; `ui-tui/src/__tests__/usePmDiscovered.test.ts`, `pmSection.test.tsx`.
