# Manifold Public 120 Binary Benchmark Corpus

This frozen corpus contains 120 public Manifold binary markets that were resolved when captured.

- Source API: `https://api.manifold.markets/v0/search-markets?term=&filter=resolved&contractType=BINARY`
- Capture date: 2026-05-21
- Packaged dataset: `manifold_public_120_binary.csv`
- Built-in benchmark name: `builtin:manifold-public-120-binary`
- Included fields: source market id, title, public URL, forecast timestamp, close time, resolution time, market probability, outcome, and description.

The market probability is preserved as both the replayed probability and a `market:manifold` baseline so the local benchmark can verify scoring and paired baseline reporting without a live API call. Each case also includes a `naive_0_5:auto` baseline.

This corpus is benchmark substrate, not proof that the agent beats markets or superforecasters. It is useful for checking that the ledger, backtest replay, source provenance, and baseline-comparison layers can handle a larger real-world resolved-question set.
