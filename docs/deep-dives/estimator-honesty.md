# The Honesty Doctrine

This is the fork's signature idea. A forecasting desk that fabricates one number
has poisoned the well: a 50% conjured for a dead outcome, a 98% read off a lone
ask, a `0.0000` born from an empty API payload — each is a lie the desk would
then *reason over*, decompose, and commit. So the market/data layers hold one
rule above convenience:

> **A number the market did not actually assert is never manufactured. Absence
> is `None`, and `None` renders "—". The honest answer to "what does the market
> think?" is often "it hasn't said."**

Every guard below was earned the hard way — most trace to a specific render the
operator caught on the tape. This page is the taxonomy: each **fabrication
class** is the lie it would tell, the **guard** that kills it, and the **test**
that pins it so it can never come back. The market plumbing these guards live in
is documented separately in [prediction-markets.md](prediction-markets.md); this
page is only about the honesty.

The doctrine has a structural spine worth stating first, because half the classes
below are corollaries of it:

- **One canonical price→probability rule.** `honest_yes_mid(yes_bid, yes_ask,
  last_price)` in `forecasting/pm/model.py` is the *single source of truth*. The
  market model (`PMMarket.yes_mid`), the aggregation layer, and the streaming
  wire all delegate to it, so no consumer can re-derive a softer number.
- **`None` NEVER `0`.** Stated as law at the top of
  `forecasting/marketdata/model.py`. A missing measurement is `null`; the TUI
  paints it "—". A zero is a *measured* zero or it does not appear.

---

## The fabrication taxonomy

### 1. Degenerate books — the phantom 50%

| | |
| --- | --- |
| **The lie** | A book with `bestBid=0 / bestAsk=1` (nobody has quoted the outcome) has a "midpoint" of 0.50. Rendered naively, a 12-outcome event shows **50% across the board** and the book sums to 5.95. |
| **The guard** | `honest_yes_mid` treats a quote spread `≥ _DEGENERATE_SPREAD` (**0.90**) as noise, not a probability: it falls through to a real last trade, else honest `None`. |
| **Pinned by** | `test_pm_model.py::test_market_yes_mid_prefers_quote_then_last`; the categorical case in `test_pm_aggregate.py`. |

The midpoint of a book nobody is quoting carries no information. `PMMarket.yes_mid`
never returns the average of `[0, 1]`.

### 2. One-sided books — the lone-ask 98%

| | |
| --- | --- |
| **The lie** | A dead market with **no bid, no trades, and a lone 98¢ ask** renders as "98%". The operator caught exactly this: a duplicate RFK-Jr. market showing 98% while the real, traded twin sat under 1%. A lone ask is an *offer to sell*, not a probability. |
| **The guard** | `honest_yes_mid` only forms a mid when **both** `yes_bid` and `yes_ask` are present. A one-sided book falls through to a real last trade, else `None`. |
| **Pinned by** | `test_pm_model.py` (`bid_only.yes_mid is None`, `ask_only.yes_mid is None`, `ask_with_trade` → the trade); `test_pm_aggregate.py::test_one_sided_book_and_duplicate_labels_the_rfk_case` (RFK must read <2%). |

### 3. Placeholder `outcomePrices` — the dead-market coin flip

| | |
| --- | --- |
| **The lie** | Polymarket ships dead/placeholder child markets whose `outcomePrices` default to roughly `[0.49, 0.51]`. Trusted blindly, every untraded outcome reads as a coin flip. |
| **The guard** | `parse_market` (`forecasting/pm/polymarket.py`) only reads the YES-oriented `outcomePrices` when **real volume** backs the market: `if prices and (volume or 0.0) > 0.0`. Zero-volume → no estimate from prices. |
| **Pinned by** | `test_pm_polymarket.py` parser fixtures. |

### 4. Kalshi `last_price=0` — "no trade" is not "0%"

| | |
| --- | --- |
| **The lie** | On Kalshi `last_price = 0` means **no trade has happened yet**, not a 0% probability. Passed through as `0.0`, every un-traded contract renders "0.00%" — the same fabrication class as placeholder prices. |
| **The guard** | `_nonzero_price` (`forecasting/pm/kalshi.py`) maps a `≤ 0` last price to `None`. The streaming path (`parse_kalshi` in `stream_wire.py`) repeats the check: `if last is not None and last <= 0.0: last = None`. |
| **Pinned by** | `test_pm_kalshi.py`. |

### 5. Closed-child terminal pricing — `lastTradePrice` is not YES-oriented

| | |
| --- | --- |
| **The lie** | A *resolved* Polymarket child market still carries a `lastTradePrice`, which can be the NO-side redemption print. The operator's catch: **Peru winning the World Cup rendered 100%** off `lastTradePrice=1` while `outcomePrices` correctly said YES=0. |
| **The guard** | When `closed` is true, `parse_market` treats the market as resolved: it **voids the book entirely** (`yes_bid = yes_ask = None`, any leftover one-sided asks are junk) and takes the terminal truth from the YES-oriented `outcomePrices`, never `lastTradePrice`. |
| **Pinned by** | `test_pm_polymarket.py` closed-market fixtures. |

Open markets prefer the YES-oriented `outcomePrices` over the direction-ambiguous
`lastTradePrice` too, keeping `lastTradePrice` only as a final fallback.

### 6. Unearned normalization — sum-to-1 must be *earned*

| | |
| --- | --- |
| **The lie** | De-vigging a categorical event to sum-to-1 is only valid over a **complete, mutually-exclusive partition**. Applied to an open-ended field or a truncated outcome list, normalization overstates *every* listed outcome (the missing mass gets silently redistributed onto the visible rows). |
| **The guard** | `build_distribution` (`forecasting/pm/aggregate.py`) normalizes only when `partition_ok`: the event is `mutually_exclusive` **and** the raw book sum sits in the sane band `[0.85, 1.25]`. Outside that, it shows **raw prices** with an honest note (`"not a guaranteed partition"` / `"looks incomplete"`), and the `PMDistribution.normalized` flag records which happened. |
| **Pinned by** | `test_pm_aggregate.py::test_normalization_is_earned_not_assumed` (open-ended → raw; truncated → raw+note; sane → normalized). |

This is the epistemic contract in one line: **normalization is a claim about
completeness, and the code refuses to make that claim unless the book earns it.**

### 7. `Number('') === 0` — the BEA `0.0000` wall

| | |
| --- | --- |
| **The lie** | BEA's NIPA API rejects `Year=LAST5` (error 201) and returns an empty `Data` array. Client-side, the empty string parsed via `Number('') === 0` — so **every row shipped `0.0000`** to operators. The bug was born in a parse, not a forecast. |
| **The guard** | `num()` in `forecasting/marketdata/model.py` returns `None` for `''` (Python's `float('')` raises, closing the exact hole). The BEA provider (`providers/bea.py`) sends **two explicit years** instead of `LAST5`, filters to the headline `LineNumber == '1'`, strips grouping commas, and maps any empty/error payload to `value = None`. |
| **Pinned by** | `test_marketdata_providers.py`; the whole reason the quote math was moved server-side is so the taxonomy tests can finally *see* it (it lived in client TypeScript where they could not). |

### 8. `None` NEVER `0` — the law, with "—" rendering

| | |
| --- | --- |
| **The lie** | A provider that does not publish a column (only Yahoo carries day-range / 52-week / volume) would show a fabricated `0` for it. A division against a zero prior close would fabricate a percentage. |
| **The guard** | `Quote` (`forecasting/marketdata/model.py`) types every crossing value `float \| None`; non-publishing providers leave columns `None`. `change_columns` returns `(None, None)` unless *both* inputs are present, and `changePct` is `None` when `prev` is `0` (no divide-by-zero fabrication). `epoch_ms` maps an unknown date to the `0` "unknown asOf" sentinel the tape reads as "—", never a fabricated time. |
| **Pinned by** | `test_marketdata_service.py`, `test_marketdata_providers.py`. |

The consumer half of the law lives in the TUI: `formatPct` and friends
(`ui-tui/src/lib/pmData.ts`) render `null / undefined / non-finite` as **"—"**.
The absence is visible, not zero-filled.

### 9. Consumer re-derivation — proof by absence

| | |
| --- | --- |
| **The lie** | Even with an honest server number, a consumer that re-derives its *own* price from the raw payload reintroduces every bug above. The operator caught a **streamed empty book overwriting Putin's honest 12% with a fabricated 50%** — computed client-side. |
| **The guard** | The tick carries a server-computed `estimate` (`Tick.estimate` in `forecasting/pm/stream_wire.py`), derived through the same canonical `honest_yes_mid` — `None` when the frame carries no estimate-grade information (degenerate/one-sided books, `price_change` level deltas). Consumers **fold only that field** and never re-derive from the raw book. The proof is by *absence*: there is no price arithmetic in the TUI overlay to get wrong. |
| **Pinned by** | `test_pm_stream.py`; the single-source-of-truth delegation across `model.py` / `aggregate.py` / `stream_wire.py`. |

### 10. Stale disk-cache rows — a stale mark, not a stale estimate

| | |
| --- | --- |
| **The lie** | A cold gateway start that repaints from disk could show a stale *number* dressed as live. |
| **The guard** | `list_events_payload` (`forecasting/pm/service.py`) serves a persisted browse tape immediately with `stale=True`, then revalidates in the background. The rows always carry their **original honest estimates** — the stale marker is the *only* thing the UI changes, a subtle signal that a live refresh is in flight. A number is never edited to look fresher than it is. |
| **Pinned by** | `test_pm_service.py`. |

---

## Why this shape

Three properties make the doctrine hold under pressure:

1. **One rule, delegated.** `honest_yes_mid` is written once. Classes 1, 2, 5,
   and 9 are all *the same guard* seen from the market model, the aggregator, and
   the wire. There is nowhere to add a fourth, softer path.
2. **Server-side, so the tests can see it.** The BEA `0.0000` wall survived for
   as long as it did because it lived in client TypeScript. The quote math now
   lives in Python (`forecasting/marketdata/model.py`) precisely so the
   estimator-honesty tests can defend the invariant.
3. **Honesty is not silence.** Refusing to fabricate is paired with *saying so*:
   the `notes` on a `PMDistribution` ("raw prices shown", "removed +N pts of
   overround"), the `normalized` flag, the `liquid` per-outcome flag, and the
   "—" render all make the absence legible rather than hiding it.

The payoff is upstream: because the market layer never lies, a market component
in a forecast ([forecasting-methodology.md](../forecasting-methodology.md) §3)
is a real de-vigged number or an explicit `None` — the desk decomposes over
signal, never over a manufactured 50%.

---

## Sources

Verified against the current tree (`superforecasting-agent-snapshot`):

- `forecasting/pm/model.py` — `honest_yes_mid`, `_DEGENERATE_SPREAD`, `PMMarket.yes_mid`, `PMDistribution.normalized`.
- `forecasting/pm/polymarket.py` — `parse_market` (volume-gated `outcomePrices`, closed-child void, `lastTradePrice` fallback ordering).
- `forecasting/pm/kalshi.py` — `_nonzero_price` (`last_price=0` → `None`).
- `forecasting/pm/aggregate.py` — `build_distribution`, `_NORMALIZE_SUM_LO/HI`, earned normalization + notes.
- `forecasting/pm/stream_wire.py` — `Tick.estimate`, `parse_polymarket` / `parse_kalshi` server-side honest estimate.
- `forecasting/pm/service.py` — `list_events_payload` stale-marked disk rows keep original estimates.
- `forecasting/marketdata/model.py` — the `None` NEVER `0` law, `num`, `epoch_ms`, `change_columns`.
- `forecasting/marketdata/providers/bea.py` — the BEA trap fix (two explicit years, headline line, `None` on empty).
- `ui-tui/src/lib/pmData.ts` — the "—" rendering (consumer half of the law).
- Tests: `tests/forecasting/test_pm_model.py`, `test_pm_aggregate.py`, `test_pm_polymarket.py`, `test_pm_kalshi.py`, `test_pm_stream.py`, `test_pm_service.py`, `test_marketdata_service.py`, `test_marketdata_providers.py`.
