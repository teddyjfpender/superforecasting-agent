# Prediction Markets First-Class: Polymarket + Kalshi Integration

**Goal (operator brief):** deep integration of Polymarket and Kalshi — headlines AND order
books — under a single "Prediction Markets" provider in the Markets view, using their
LATEST APIs, fast and efficient, with: Enter opens the market page, price history,
categorical aggregation (headline row + indented outcome sub-rows forming a discretized
distribution), websocket streaming where it pays, API-key entry inside the add-data flow,
clean non-monolithic modules, and first-class structured access for the agent (no more
fuzzy evidence pulls).

## API research findings (2026-07, verified against current docs)

### Polymarket — three services, market data all PUBLIC
- **Gamma** `https://gamma-api.polymarket.com` — discovery. `GET /events` (nested
  `markets[]` — a negRisk/categorical EVENT is the discretized distribution; each child
  market carries `groupItemTitle` as the outcome label and `clobTokenIds`), `GET
  /events/{id}`, `GET /markets?...`, slug + tag queries. No auth. ~4,000 req/10s.
- **CLOB** `https://clob.polymarket.com` — pricing. Public: `GET /book?token_id=`,
  `GET /midpoint?token_id=`, `GET /spread?token_id=`, `GET /prices-history?market=<token>`
  (+interval/fidelity/startTs/endTs). Auth needed only for TRADING (we never trade).
- **WS** `wss://ws-subscriptions-clob.polymarket.com/ws/market` — public market channel;
  subscribe `{"type":"market","assets_ids":[...]}`; pushes `book`, `price_change`,
  `tick_size_change`. 5 connections/IP — ONE shared connection, multiplexed subscriptions.

### Kalshi — REST market data PUBLIC, WS requires the authed handshake
- **REST** `https://api.elections.kalshi.com/trade-api/v2` — `GET /events`
  (`with_nested_markets=true`: an EVENT's markets[] are the categorical buckets — Kalshi's
  hierarchy is literally series → event → outcome markets), `GET /markets`,
  `GET /markets/{ticker}/orderbook`,
  `GET /series/{series_ticker}/markets/{ticker}/candlesticks`
  (`period_interval` ∈ {1, 60, 1440} minutes; OHLC for yes_bid/yes_ask/price + volume +
  open_interest). **No auth for market data** → the default keyless experience works.
- **WS** `wss://api.elections.kalshi.com/trade-api/ws/v2` — handshake REQUIRES
  `KALSHI-ACCESS-KEY` (key id) + `KALSHI-ACCESS-SIGNATURE` (RSA-PSS-SHA256 over
  `timestamp + "GET" + "/trade-api/ws/v2"`) + timestamp. Public channels (`ticker`,
  `trade`, lifecycle) need no per-channel authorization but DO need the authed session.
  → streaming for Kalshi is an OPT-IN upgrade unlocked by the key pair; REST polling is
  the keyless fallback.

## The architectural decision: one Python implementation, two consumers

The existing Markets view fetches series client-side (`ui-tui/src/lib/marketFetch.ts`,
catalog in `content/marketProviders.ts`, config `markets.json`). Prediction markets
BREAK that pattern deliberately: the agent (Python) is a first-class consumer, so the
clients live ONCE in Python; the TUI consumes gateway RPCs; streaming rides the gateway's
existing event push. The old `source_adapters` polymarket/kalshi evidence paths remain
but the tool's structured action routes through the new service (one source of truth).

## Module layout (non-monolithic — hard rule)

```
forecasting/pm/                     # NEW package. No file > ~400 lines.
  __init__.py                       # public facade re-exports
  model.py                          # frozen dataclasses: PMEvent, PMMarket, PMOrderBook,
                                    #   PMHistoryPoint, PMDistribution (+ to_dict)
  polymarket.py                     # Gamma+CLOB client (stdlib urllib, bounded timeouts,
                                    #   TTL cache hooks; NO trading endpoints)
  kalshi.py                         # REST client + rsa signer helper (signer used by ws
                                    #   only; cryptography import LAZY + optional)
  aggregate.py                      # event -> PMDistribution: yes-mids, de-vig normalize
                                    #   (reuse bayes_toolkit devig math), outcome ordering,
                                    #   headline synthesis (top outcome, n, total volume)
  history.py                        # normalize both venues' history to [{ts, p}] +
                                    #   downsampling for TUI sparklines
  stream.py                         # ws clients (polymarket public; kalshi authed),
                                    #   ONE connection per venue, subscription registry,
                                    #   callback bus, auto-reconnect w/ backoff, clean stop
  service.py                        # PMService facade: search/list_events/event_detail/
                                    #   orderbook/history — TTL caches (list 30s, detail
                                    #   15s, history 5m), stale-while-revalidate
tui_gateway/pm_rpc.py               # NEW file (server.py only registers it): RPCs
                                    #   pm.list {venue?, query?, tag?, limit} -> events+distributions
                                    #   pm.detail {venue, event_id} -> full event + outcomes
                                    #   pm.book {venue, market_id} -> normalized book
                                    #   pm.history {venue, market_id, range} -> points
                                    #   pm.stream.start/stop {venue, market_ids} -> gateway
                                    #     events pm.tick {venue, market_id, price/book delta}
tools/forecasting_tool.py           # ONE action `pm_query` {mode: search|event|book|history,
                                    #   ...} -> structured PM data via PMService (thin;
                                    #   module-level imports; the agent's first-class pull)
ui-tui/src/lib/pmData.ts            # gw-backed fetch + types mirroring the RPC contracts
ui-tui/src/components/marketsView   # 'Prediction Markets' provider/filter: event headline
                                    #   rows + indented outcome sub-rows (▸ expand/collapse),
                                    #   detail pane = distribution bars + book (bid/ask
                                    #   ladders) + history sparkline; Enter opens market URL
                                    #   (existing open-URL seam); pm.tick updates in place
```

## Key management
- Polymarket: none needed (read-only public).
- Kalshi: needed ONLY for websocket streaming. `/api-key set kalshi` flow extended to
  capture BOTH the key id and the RSA private key PEM (stored 0600 under the workspace,
  path recorded in .env style like other providers). The add-data/provider-enable flow in
  the Markets view surfaces this: enabling streaming without a key shows the exact
  command; REST polling works regardless.

## The distribution contract (the headline+sub-rows ask)
- An EVENT with n>1 markets renders as: headline row (event title, aggregate = top
  outcome label + its de-vigged prob, total volume, close time) and indented sub-rows
  (outcome label, de-vigged prob, raw yes bid/ask, volume). Probs are de-vigged so they
  sum to ~1 (label raw vs de-vig honestly in the detail pane). Binary events render as a
  single row (their own headline).
- De-vig: multiplicative normalization over yes-mids (consistent with the existing
  bayes_toolkit devig used by the desk) — one shared implementation in aggregate.py.

## Efficiency rules
- ONE Gamma /events page call per list refresh (nested markets included); ONE Kalshi
  /events?with_nested_markets=true call. Books and history fetch ON DEMAND (selection).
- TTL caches in PMService; ws ticks invalidate the touched entries only.
- No polling loops in the TUI: the gateway streams pm.tick; the view repaints rows in
  place. REST fallback poll (30s, list only) when no stream is active.

## Test strategy
- Recorded-fixture JSON for both venues (real response shapes captured once into
  tests/fixtures/pm/) — clients tested against fixtures, NEVER live network in tests.
- aggregate.py: hand-checkable de-vig cases (sum-to-one, vig removal, degenerate
  one-market events, zero-liquidity outcomes ranked last).
- stream.py: fake ws transport (callback bus contract, reconnect/backoff, stop).
- RPC handlers: gateway test patterns; TUI: harness renders of headline+sub-rows,
  expand/collapse, book pane, Enter-open, tick repaint.

## Slices
1. **S1** `forecasting/pm/` package complete w/ fixtures + tests (no gateway/TUI).
2. **S2** gateway pm_rpc.py + stream bridge + api-key flow extension + doctor surface.
3. **S3** TUI: provider filter, rows/sub-rows, detail pane (distribution + book +
   history), Enter-open, tick updates, add-data flow w/ key hint.
4. **S4** agent: pm_query tool action + protocol/skill sentence + README line.
Review lenses: API-contract correctness (against THIS doc + live docs), epistemic
(de-vig math, raw-vs-devig labeling, no fabricated liquidity), efficiency (call counts,
cache hits, single ws connection), TUI craft (the established design rules).
