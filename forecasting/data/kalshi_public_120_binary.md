# Kalshi Public 120 Binary Benchmark Corpus

This frozen corpus contains 120 public Kalshi binary markets that were finalized when captured.

- Source API: `https://external-api.kalshi.com/trade-api/v2/markets?status=settled&limit=200`
- Capture date: 2026-05-26
- Packaged dataset: `kalshi_public_120_binary.csv`
- Built-in benchmark name: `builtin:kalshi-public-120-binary`
- Included fields: source market ticker, title, public URL, forecast timestamp, close time, settlement time, market probability, outcome, and rules text when present.

The market probability is preserved as both the replayed probability and a `market:kalshi` baseline so the local benchmark can verify scoring, external source-family readiness, and paired baseline reporting without a live API call. Each case also includes a `naive_0_5:auto` baseline.

This corpus is benchmark substrate, not proof that the agent beats markets or superforecasters. The captured markets are recent public Kalshi settlements and include low-liquidity markets; they are useful for testing source provenance and readiness diversity rather than for making skill claims.
