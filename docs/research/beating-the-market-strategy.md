# Beating the Market: A Strategy for a Provable Step-Function Edge

**Date:** 2026-06-28 · **System:** hermes-agent superforecasting fork (`superforecasting-agent-snapshot`)
· **Status:** strategy / pre-registration · **Companion:** [ForecastBench Grounding Study](forecastbench-grounding-study.md)

---

## Abstract

Our closed-book agent currently *matches but does not beat* a de-vigged prediction-market
baseline: over 240 resolved ForecastBench market-probability questions it scores a mean Brier of
**0.1668** versus the market freeze price's **0.1629** (edge **−0.0039**, market slightly better),
and a simplex agent+market ensemble puts **all weight on the market** (agent weight 0.0, 95% CI
[0.0, 0.325]). The grounding study traced all of this to a single cause: the agent was *shown the
market price and anchored on it*. This document specifies how to convert that diagnosis into a
**provable, step-function improvement** over the market. The thesis: the agent's edge is not
recalibration of a market-anchored number (that ceiling is the market itself) but the **manufacture
of orthogonal signal** — an independently-reasoned forecast (market-hidden), augmented by a
fresh-evidence search loop the market has not yet priced, then *pooled* with the de-vigged market in
log-odds space. We define the referee's bar (the metrics + significance tests that constitute proof,
all already implemented), map each engineering lever to a market-beating mechanism with a falsifiable
edge hypothesis and a measurement plan, prioritize by expected Brier-skill-per-effort, identify the
question classes where markets are structurally weak, and give a pre-registered experimental protocol
with arms, baselines, metrics, and a power calculation. We are explicit about where the edge is thin.

This document is grounded both in an internal audit of our codebase and in the external forecasting
literature (GJP/Tetlock, the extremizing-the-crowd line, Halawi et al., the AIA Forecaster + ForecastBench
results, and the prediction-market-inefficiency studies). §0 surveys that literature and maps each finding
to a decision in this strategy; the rest of the document is unchanged in spirit but now cites the prior
work that supports — or warns against — each mechanism.

---

## 0. Prior work & literature grounding

This section anchors the strategy in the published evidence. The short version: **the academic
literature does not say "an LLM agent beats prediction markets." It says the opposite for liquid
markets — and it tells us precisely where, and only where, an agent adds value: as an orthogonal
*minority correction* pooled onto a market anchor, concentrated in the thin/slow/numeric seams, proved
with paired, leakage-controlled, proper-scoring tests.** Our codebase already implements this design;
the literature's role here is to certify that we built the right thing and to keep us honest about how
small and fragile the edge is.

### 0.1 The market is a strong, efficient baseline — start skeptical

- **Prices are informationally efficient even when thin.** Tetlock, *Liquidity and Prediction Market
  Efficiency* (2008), finds prices are efficient with thin markets, small stakes, and restricted
  participants — and, counter-intuitively, **liquidity does *not* improve calibration**; liquid
  securities are no better calibrated than illiquid ones, and added liquidity *sometimes increases*
  price deviations (naïve limit-order traders bet against the informed and slow the price's response).
  *Implication for us:* the number to beat is the **de-vigged market price**, and most claimed edges
  evaporate against it. This is the empirical justification for our M0 baseline and for our refusal to
  claim a general "we beat markets" result.
  [Tetlock 2008](https://business.columbia.edu/sites/default/files-efs/pubfiles/3098/Tetlock_SSRN_Liquidity_and_Efficiency.pdf)
- **ForecastBench reality check.** Across 17 frontier models the best LLM still *significantly*
  underperforms superforecasters (p<0.001): superforecaster difficulty-adjusted Brier ≈0.081 vs best
  LLM (GPT-4.5) ≈0.101; on a 200-item subset, median superforecaster 0.093 vs top LLM 0.119. Ordering:
  expert forecasters > LLMs > public > worst LLMs.
  [ForecastBench, arXiv:2409.19839](https://arxiv.org/abs/2409.19839)

### 0.2 The AIA Forecaster — the single most direct precedent (and it is humbling)

The AIA Forecaster technical report (Bridgewater AIA Labs, Nov 2025) is the paper our stack most closely
mirrors, and its results define our ambition:

- On **liquid** prediction markets the standalone agent **loses**: AIA Brier **0.1258 vs market 0.1106**
  (~13–15 bps worse). It only matches/beats the market on easier/thinner sets.
- On **no-market judgmental** questions the agent earns its keep: AIA reaches **superforecaster parity**
  on ForecastBench (FB-7-21: 0.1076 vs supers 0.1110; FB-8-14: 0.1099 vs 0.1152).
- **The edge is the ensemble, not the agent.** A simplex-constrained (convex, Brier-minimizing) blend of
  {agent, de-vigged market} scores **0.106 < market 0.1106**. Learned weights on liquid markets land at
  **~33% agent / 67% market** (they flip to ~87% agent on no-market sets). The demonstrable edge is a
  **minority correction on a market anchor**.
- **Search is the dominant lever** (0.114 with search vs 0.123 without) — *but* handing the model the
  market price fakes ~42% of that "search gain," i.e. most of what the search loop discovers is already
  in the price. Drivers: agentic news search, a ~10-agent ensemble + supervisor that searches to resolve
  disagreement, and Platt scaling to undo LLM hedging (which they prove is **Generalized Log-Odds
  Extremization** at fixed α=√3≈1.73). They explicitly **do not** stack Platt on top of the
  market-blend — recalibrating a different aggregation method erases the edge.
  [AIA Forecaster, arXiv:2511.07678](https://arxiv.org/abs/2511.07678)

Our `forecasting/market_ensemble.py` encodes these numbers verbatim (LLM 0.126 / market 0.111 / blend
0.106) and correctly **refuses to Platt-extremize the blend** — that invariant is the AIA finding made
load-bearing, not an accident. Every "where the edge is thin" caveat in §5 traces to this paper.

### 0.3 Where an LLM *does* add signal — the edge regime (Halawi et al.)

Halawi et al., *Approaching Human-Level Forecasting* (NeurIPS 2024), localizes the win. Overall the LLM
**loses** to the crowd (Brier 0.179 vs 0.149), but it **beats** the crowd in a narrow selective regime:
when the crowd is **uncertain** (crowd prob in 0.3–0.7), **early** in the question's life, with **≥5
relevant articles** retrieved (their Condition 4: 0.240 vs 0.247, >1.5 SE, but only ~22% of forecasts).
The LLM's documented weakness — it "rarely outputs low probabilities" (RLHF hedging toward 0.5) — is the
exact failure that extremization/Platt is built to fix.
[Halawi et al., arXiv:2402.18563](https://arxiv.org/abs/2402.18563)

*Implication for us:* concentrate **high agent weight** only where (i) no liquid market exists or the
market/crowd is uncertain (implied prob 0.3–0.7), (ii) early in the question's life, (iii) with the
fresh-search loop returning **≥5 independent relevant sources**. This is a natural `lesson:*` rule and a
panel/quorum trigger, and it sharpens §3's target-class table.

### 0.4 Extremizing the crowd — powerful, fit-dependent, and fragile

- **The mechanism (Satopää, Baron, Mellers, Ungar, Tetlock 2014).** Each forecaster sees only *part* of
  the information, so the simple average is systematically **under-confident** (too near 0.5). The
  optimal fix transforms the average in **log-odds space** and pushes it toward the nearest extreme by a
  coefficient `a>1`. The optimal `a` is a function of **information overlap**: low overlap / high
  diversity ⇒ large `a`; high overlap (re-used facts) ⇒ a≈1 (don't extremize). This is why **averaging
  log-odds (geometric mean of odds) is itself mildly extremizing** and beats averaging probabilities.
  [Satopää et al., arXiv:1501.06943](https://arxiv.org/pdf/1501.06943) ·
  [Pemantle/Satopää](https://www2.math.upenn.edu/~pemantle/papers/forecasting.pdf)
- **Log-odds / geometric-mean-of-odds pooling beats arithmetic averaging.** Log pooling is the unique
  externally-Bayesian operator, minimizes average KL-divergence to the experts, and is optimal for
  log-loss. On Satopää's GJP data the (extremized) geometric-mean-of-odds had the best Brier; even
  un-extremized it robustly beat the arithmetic mean and the median. **This is the right space in which
  to pool the agent with the market.**
  [EA Forum: geometric mean of odds](https://forum.effectivealtruism.org/posts/sMjcjnnpoAQCcedL2/when-pooling-forecasts-use-the-geometric-mean-of-odds)
- **It is fragile and must be FIT, never assumed.** Extremizing only works on a *diverse, partly
  independent* crowd; on a team of already-strong, communicating forecasters the optimal `a`≈0. Several
  researchers now think the spectacular GJP extremizing result was partly a tournament-era fluke. On
  ~850 Metaculus binary questions an extremizing factor of **2.5 hurt** while **1.5 helped** — the
  optimal factor varies by community/period and **must be fit on resolved data with a significance
  gate**. This is exactly why our √3 Platt (Lever D / GATE 1) is gated behind the LOO α-sweep and
  refused for the market-blend.
  [EA Forum, ibid.](https://forum.effectivealtruism.org/posts/sMjcjnnpoAQCcedL2/when-pooling-forecasts-use-the-geometric-mean-of-odds)

### 0.5 What actually makes superforecasters better — and what the edge is *made of*

- **Five drivers (Mellers et al. 2014, 2015).** Supers average Brier ~0.17 vs ~0.26 for regulars; the
  GJP elite weighted+extremized aggregate beat an unweighted crowd by 60%+ and beat professional
  analysts (with classified data) by ~25–30%. Drivers, in rough order: (1) past in-domain performance
  (year-to-year skill correlation ~0.65 — skill is **real and persistent**, not regression to the mean),
  (2) **frequency of belief updating**, (3) deliberation time, (4) teaming, (5) intelligence + Active
  Open-Mindedness.
  [Mellers 2014](https://learnmoore.org/papers/Mellers%20et%20al%202014.pdf) ·
  [Mellers 2015](https://web.stanford.edu/~knutson/jdm/mellers15.pdf)
- **The BIN decomposition (Satopää, Salikhov, Tetlock, Mellers, *Management Science* 2021).** The
  super-vs-regular gap is ~**50% noise reduction**, ~25% information gain, ~25% bias reduction. The
  striking implication: most measurable improvement is **reducing noise (inconsistency)**, not secret
  information. *For an AI this is encouraging* — determinism, seeded bootstraps, and ~10-agent
  ensembling are exactly noise-reduction tools. Our reproducible seeded bootstrap in
  `market_ensemble.py` is doing real BIN-noise work, not just engineering hygiene.
  [BIN model, MS 2021](https://dlnext.acm.org/doi/10.1287/mnsc.2020.3882)
- **Frequent, fine-grained updating is causal.** GJP: more updates ⇒ better standardized Brier; supers
  were more accurate at the outset *and* improved faster as news arrived; **rounding** supers'
  probabilities to coarser buckets **degrades** Brier — they extract real signal at the 0.01 level.
  *Practice:* re-forecast on every material news event, in fine increments (our autonomous reforecast,
  task #137). [AI Impacts: GJP practices](https://aiimpacts.org/evidence-on-good-forecasting-practices-from-the-good-judgment-project/)
- **Reference-class / outside-view is the highest-value single move.** In GJP, predictions tagged with
  comparison classes averaged Brier ~0.17 vs ~0.26 — a large, clean gap; a one-hour outside-view/debias
  training module produced gains persisting ≥1 year. This underwrites Lever D's base-rate anchoring and
  Lever E's outside-view-first reasoning-sequence hook.
  [AI Impacts, ibid.](https://aiimpacts.org/evidence-on-good-forecasting-practices-from-the-good-judgment-project/)

### 0.6 Diversity beats individual accuracy — and the accuracy–correlation threat

- **Why diversity > accuracy in aggregation.** Aggregate error = average individual error − diversity, so
  a pool of mediocre-but-**decorrelated** forecasters beats a pool of strong-but-correlated ones. The
  "silicon crowd" work confirms it: a median of 12 diverse LLMs scores Brier 0.20 — statistically
  indistinguishable from the human crowd's 0.19 (p=0.85) — while no single model does. When LLMs are
  shown the crowd median they improve, but **mechanically averaging human+machine beats the model's own
  self-update** — direct evidence for *pooling* the price rather than feeding it into the prompt.
  [Silicon crowd, PNAS Nexus](https://pmc.ncbi.nlm.nih.gov/articles/PMC11800985/) ·
  [Information-diversity, Sci. Adv.](https://www.science.org/doi/10.1126/sciadv.adp1528)
- **The accuracy–correlation effect — our biggest hidden risk** (Jeddi, Segovia-Martin,
  Servan-Schreiber, *Phil. Trans. R. Soc. B*, 2026). As LLMs get more accurate they get more
  **correlated** with humans *and with each other*, and they share **failure modes** — "humans and LLMs
  appear to be learning not just the same answers, but the same failure modes." Accuracy gains do **not**
  buy cognitive diversity; you get **algorithmic monoculture**. Since our entire edge rests on
  *orthogonal* signal, a homogeneous LLM panel that merely reproduces the consensus has nothing to pool
  in. **Diversity must be engineered and MEASURED, not assumed** — this is the missing instrument behind
  Lever A's orthogonality requirement and tasks #181/#186.
  [Royal Society 2026](https://royalsocietypublishing.org/rstb/article/381/1948/20240456/481367/Crowdsourced-versus-large-language-models)

### 0.7 Where markets are structurally beatable (the exploitable seams)

The honest size of the prize: on ForecastBench FB-Market (76 q) the **superforecaster median Brier 0.0740
vs market consensus 0.0965 vs public 0.1035** — even elite humans beat the market by only ~0.02–0.03
Brier. The seams where that gap lives:

- **Favorite–longshot bias.** Longshots over-priced, favorites under-priced — robust in sports and
  present on crypto prediction markets (Polymarket 90c contracts resolve YES *less* than 90% of the time;
  10c contracts *more* than 10%). *Strategy:* fade cheap longshots / back underpriced favorites, but the
  bias is small in cents so fees/spread eat it outside the deep tail.
  [Quantpedia](https://quantpedia.com/systematic-edges-in-prediction-markets/)
- **Slow / over-reactive information incorporation.** The 2024 US-election study found inefficiency
  *increased* in the final two weeks (when info was richest) and 58% of Polymarket national markets
  showed **negative day-to-day serial correlation** (short-term reversals = over-reaction, not smooth
  convergence). The LBS/Yale study (1.72M accounts) finds only **~3% of traders drive price discovery**;
  the consensus **lags** news until that informed minority moves it. *Strategy:* a fast fresh-search loop
  that reacts in minutes is the single most defensible real-time edge (Lever B). *Skeptic flag:* ~60% of
  apparent winners regress to losers out-of-sample — "I reacted fast once" is luck until proven on a
  pre-registered sample.
  [Good Authority](https://goodauthority.org/news/the-perils-of-election-prediction-markets/) ·
  [CoinDesk: 3% of traders](https://www.coindesk.com/markets/2026/04/26/only-3-of-traders-drive-prediction-markets-accuracy-not-the-crowd-study-finds)
- **Long-horizon time-value decay** biases cheap long-dated YES upward (locked capital earns zero;
  return asymmetry favors longs at low prices). Theory predicts ~6pp at a 2-year horizon — but the
  paper's *own* simulation found the realized effect ≈0.72pp, and interest-bearing collateral erased
  ~83% of it. **Genuine in direction, sub-1pp in magnitude on liquid venues.**
  [arXiv:2602.21091](https://arxiv.org/html/2602.21091)
- **Thin / illiquid markets & capped venues.** Kyle's λ on Polymarket fell from 0.518 early to 0.01 by
  October — price impact (and mispricing) is concentrated in low-volume, early markets. PredictIt's
  $850/contract cap + 10%/5% fees let mispricings persist (Shleifer–Vishny limits-of-arbitrage made
  concrete). *Strategy:* treat low-volume/early/capped venues as where the market signal is **weakest** —
  down-weight (or drop) the market term in the pool; don't build a cross-venue arb bot (windows are
  seconds, bots win).
  [Anatomy of Polymarket, arXiv:2603.03136](https://arxiv.org/html/2603.03136v1) ·
  [PredictIt case study](https://www.lesswrong.com/posts/c3iQryHA4tnAvPZEv/limits-of-current-us-prediction-markets-predictit-case-study)
- **Dataset / numeric questions markets don't cover** — the biggest *structural* gap. Real-money venues
  quote binary YES/NO; full continuous distributions exist only on competition platforms (Metaculus) and
  experimental distribution markets. There is **no liquid price to beat**, so a calibrated distributional
  forecaster wins by construction — but label this honestly as "beating the **absence** of a market," a
  weaker claim than beating a liquid price. This is §3's dataset/numeric class (needs CRPS, not Brier).
  [Paradigm: distribution markets](https://www.paradigm.xyz/2024/12/distribution-markets)

### 0.8 The profit story is real but fragile (and not our headline)

*Beyond Accuracy: Can LLM Forecasters Profit on Prediction Markets?* (OpenReview): the strongest LLM was
accuracy-**indistinguishable** from the market yet earned higher realized returns — the edge "comes
entirely from **losing less when wrong**, exploiting behavioral biases rooted in human psychology," and a
within-LLM-crowd-**agreement** confidence filter raised Sharpe/ROI/PnL further. But PolyBench (live
Polymarket) is the reality check: only 2 of 7 models made positive returns, the edge lived in Politics
and **died in crypto/speculative**, and **order-book slippage collapses profitability above ~$500
capital**. *For us:* an edge that lives on persistent human irrationality decays as markets mature and as
other bots arbitrage the same biases; if we ever trade, **capacity is the binding constraint, not
accuracy**. We do **not** make a profit claim the headline.
[Beyond Accuracy](https://openreview.net/forum?id=TSA5kRUKZv) ·
[PolyBench, arXiv:2604.14199](https://arxiv.org/html/2604.14199v1)

### 0.9 Synthesis — what the literature tells us to build (and not to claim)

| Finding | Source | Our decision |
|---|---|---|
| Liquid markets are efficient; standalone agent loses ~13bps | Tetlock 2008; AIA | M0 = de-vigged market; **no** standalone-beats-liquid-market claim |
| Edge = convex/log-odds **pool**, agent as **minority correction** (~33% on liquid) | AIA; silicon crowd | Lever C ensemble is the proof surface; if agent weight >50% on a liquid market, suspect leakage |
| Search is the dominant lever, but the price fakes ~42% of it | AIA | Lever B + keep the price **out** of closed-book reasoning (Lever A); attribute gain via 2×2 ablation |
| Pool in **log-odds**, do **not** recalibrate the blend | Satopää; AIA | `market_ensemble.py` invariant preserved |
| Extremize only a **diverse** panel; **fit** the coefficient | Satopää; Metaculus | √3 Platt gated behind LOO α-sweep + significance (Lever D / GATE 1) |
| ~50% of the edge is **noise reduction** | BIN 2021 | Determinism + seeded bootstraps + ensembling are first-class |
| Agent wins only when crowd uncertain (0.3–0.7), early, ≥5 sources | Halawi | High-agent-weight gate; `lesson:*` rule; §3 sharpened |
| Diversity must be **measured**, not assumed (monoculture risk) | Royal Society 2026 | Pairwise panel correlation + agent-vs-market **residual** correlation as first-class metrics |
| Seams: favorite-longshot, over-reaction, thin/long-horizon, numeric | multiple | §3 target-class table; down-weight market in thin/capped venues |
| Profit edge is fragile, capacity-bound | Beyond Accuracy; PolyBench | Not a headline; if trading, size to liquidity, condition on agreement |

**The headline we can defensibly publish:** *our agent+market log-odds pool lowers Brier vs the de-vigged
market on resolved data with p<x, and our selective bets are positive-EV in the documented inefficient
regimes* — **not** a general "we beat markets." Treat any apparent broad edge as a leakage bug until
proven otherwise.

---

## 1. Thesis and the bar for "provably step-function better"

### 1.1 Thesis

> The market is a near-optimal aggregator of *already-priced* information. We cannot beat it by
> recalibrating a forecast that was itself anchored on the market price — that path's ceiling **is**
> the market. We beat it only by contributing **orthogonal signal**: (a) an independently-reasoned
> estimate the market does not see (de-correlated by construction via the market-hidden arm), and
> (b) fresh evidence the market has not yet absorbed (the supervisor search loop), then **pooling**
> the two de-correlated signals (agent + de-vigged market) in log-odds space. The ensemble theorem
> (a convex/log-odds blend beats both inputs when the components carry independent error) is the
> mechanism; orthogonality is the precondition; the question classes where the market is slow or
> thin are where the precondition is easiest to satisfy.

This reframes the goal. "Step-function" does **not** mean a larger α on a market-anchored number.
It means moving the agent off the market's information set entirely, so its errors stop being a noisy
copy of the market's errors and start being *complementary* to them. Complementarity is the thing the
simplex ensemble measures, and it is the thing that was absent (weight 0.0) precisely because the
agent saw the price.

### 1.2 The referee's bar — proof, not vibes

A referee evaluating "the harness is a step-function better than the market" would demand the
following, **all of which we already compute**. We commit to these as the acceptance criteria. Each is
grounded in the accepted forecasting-evaluation literature (citations inline), so a reviewer's objection
maps to a specific test we already run.

**The accepted-metric stack the literature requires** (and our implementation of each):

- **Strictly proper scoring rule as PRIMARY; calibration as a DIAGNOSTIC, never the reverse.** The
  headline must be a proper score (Brier/quadratic/log) so that honest reporting is score-maximizing
  (Gneiting & Raftery 2007, JASA). ECE/MCE are **not** proper — a constant base-rate forecaster has zero
  calibration error, and binned ECE is non-monotonic in true quality and binning-dependent. *Ours:*
  Brier is primary throughout; `signed_calibration_error`/ECE are explicitly **diagnostics** (criterion 4
  below), never the headline.
  [Gneiting & Raftery 2007](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf)
- **Skill vs the MARKET reference, not raw score** — Brier Skill Score `BSS = 1 − BS_agent/BS_market`,
  with the market price **at forecast time** and **de-vigged** as the null. (Liu et al. 2007 is the
  canonical skill-vs-reference + sampling-distribution citation.) *Ours:* the paired edge `δ_i` (below)
  is the BSS numerator made paired; M0 is the de-vigged freeze price.
  [Liu et al. 2007](https://journals.ametsoc.org/view/journals/wefo/22/5/waf1034_1.xml)
- **Diebold–Mariano as the parametric twin of the bootstrap.** DM (1995) tests H0: E[loss
  differential]=0 with a HAC/Newey-West long-run variance to absorb the serial *and* contemporaneous
  correlation that resolving questions over time induces. Diebold's own retrospective warns DM is
  asymptotic and abused on nested models / tiny samples, so a **block/clustered bootstrap** is safer for
  correlated tournament questions. *A referee wants BOTH a bootstrap and a HAC-robust DM, and the
  dependence structure named.* **Action item:** add a HAC-robust DM cross-check alongside our bootstrap,
  and use a **block** bootstrap so question correlation doesn't fake-tighten the CI (our effective n ≪
  question count).
  [DM "Twenty Years Later"](https://www.researchgate.net/publication/256033714_Comparing_Predictive_Accuracy_Twenty_Years_Later_A_Personal_Perspective_on_the_Use_and_Abuse_of_Diebold-Mariano_Tests)
- **Murphy decomposition to LOCALIZE the edge.** `BS = Uncertainty − Resolution + Reliability`. A
  credible "we beat the market" story attributes the BSS gain to higher **Resolution** (you actually know
  more), **not** merely lower Reliability — because a referee can replicate a reliability gain by
  trivially **recalibrating the market price**. *Action item:* run the Murphy decomposition on every
  backtest, with a variance estimate, and **require the gain to live in the Resolution term**; our Platt
  sweep handles reliability, which a referee will therefore discount. (Murphy 1973; Siegert 2017.)
  [Siegert 2017](https://rmets.onlinelibrary.wiley.com/doi/abs/10.1002/qj.2985) ·
  [Variance of the decomposition](https://arxiv.org/pdf/1303.6182)
- **Mincer–Zarnowitz as the parametric calibration test.** Regress outcome `o` on forecast `f`:
  `o = α + βf + ε`; jointly Wald-test H0: α=0, β=1 (autocalibration); β<1 = overconfidence, α≠0 = bias —
  and the MZ coefficients **give** the recalibration map. *Action item:* report the joint MZ Wald test
  alongside the reliability diagram, not eyeballing.
- **Strictly out-of-sample / future-only is the whole ballgame for LLMs.** The fatal failure is
  memorization: an LLM "forecasting" an event it saw in training is retrieving. The accepted defense
  (Pitfalls in Evaluating LM Forecasters, arXiv:2506.00723; Kalshibench): score **only** questions whose
  resolution date is strictly after every tested model's cutoff, and collect evidence **prospectively**
  (filter by publish date on the question's open date). "Pitfalls" documents that ≥3.8% of one popular
  dataset resolved "early" (logical leakage), date-restricted retrieval **leaks the future**, cutoffs
  aren't guarantees, and "matching humans" can be **circular** (the human/market forecast is in
  training/retrieval). *Ours:* the closed-book seal + model-cutoff gate + leak-domain denylist + time-travel
  source pinning are exactly this firewall (criterion 5). **The uncalibrated leak-judge (GATE 4 / #183)
  is the one un-de-risked piece — until hand-labeled, our out-of-sample bound is unfalsifiable.**
  [Pitfalls, arXiv:2506.00723](https://arxiv.org/abs/2506.00723)
- **Pre-registration + a live prospective panel** (IARPA/GJP design; Schoenegger et al. preregistered
  RCT, ACM TIIS 2025). Referees now expect a pre-specified question universe, primary endpoint, and
  scoring/aggregation, with forecasts time-stamped and frozen before resolution and the **market price
  snapshotted at the SAME timestamp** — no look-back, no mid-tournament model swaps. *Ours:* §4 is the
  pre-registration; MarketNightly (#179) is the live panel.
- **Instantaneous, leakage-immune skill signal: consistency-arbitrage checks** (Paleka et al.,
  *Consistency Checks for LM Forecasters*, ICLR 2025). Measure an arbitrage metric over logically-related
  questions (Negation `F(P)+F(¬P)=1`, Paraphrase, Consequence `F(P)≤F(Q)`, And/Or). An internally
  inconsistent forecaster is arbitrageable, and instantaneous consistency **correlates with eventual
  ground-truth Brier** — so it is a skill gate you can run **before any market resolves** and that **no
  leakage can fake**. **Action item:** add Negation/Paraphrase/Consequence consistency checks to the
  panel/quorum as an instantaneous skill gate, paired with the resolution-based bar below.
  [Paleka et al., arXiv:2412.18544](https://arxiv.org/abs/2412.18544)

**The fragility flags a referee will probe** (and our guard for each): (1) the market baseline must be
the **de-vigged price at forecast time** — a stale/vig-inflated price manufactures fake skill (M0 is
de-vigged at freeze). (2) **Question-selection bias** — cherry-picking illiquid markets is not "beating
the market"; **pre-register and stratify by liquidity/volume** (§3/§4). (3) **Multiplicity** — testing
many configs needs the **win-rate-vs-BEST** framing (not vs-average) plus a correction (criterion 2). (4)
**Correlated questions inflate n** — use a block bootstrap (action item above). (5) A **reliability-only
gain is market-replicable** — only a Resolution gain survives (Murphy, above). (6) Tiny-n, non-Gaussian
Brier deltas make DM asymptotics unreliable — the **bootstrap is mandatory**. (7) **"Better Brier" ≠
profitable** — any drift toward an alpha claim needs a P&L backtest net of fees/slippage (a harder,
capacity-bound bar; §0.8).

The acceptance criteria proper:

1. **Paired Brier edge with a recenter-at-zero bootstrap p-value.**
   The primary statistic is the per-question paired Brier delta `δ_i = brier_market_i −
   brier_agent_i` (positive ⇒ agent better), aggregated by `_compute_paired_brier_stats` /
   `_paired_bootstrap` (`forecasting/ledger.py:12230-12322`). It reports `paired_agent_edge_mean_brier`,
   a **seeded** two-sided p-value (recenter the deltas at zero, draw `PAIRED_BOOTSTRAP_DRAWS`
   resample-means of the centered series, count the fraction with magnitude ≥ |mean_delta|, plus-one
   corrected so p is never exactly 0), and a 95% CI from the 2.5/97.5 percentiles of the *uncentered*
   resample-means. **Acceptance: the 95% CI for the agent edge excludes 0 on the side of the agent,
   and p < 0.05.** Pairing is essential — it removes question-difficulty variance, which is the
   dominant term, so the paired test has far more power than comparing two marginal Brier means. This
   recenter-at-zero paired-bootstrap procedure is the **field standard** (it is exactly what the AIA
   Forecaster uses, B=10,000 draws), so our `PAIRED_BOOTSTRAP_DRAWS=10000` / seeded / percentile-CI
   implementation is a literal port of the accepted test, not an in-house invention. **Refinement
   (action item):** make it a **block** bootstrap (cluster by question-correlation structure) so the CI
   is not fake-tightened by correlated questions, and report a **HAC-robust Diebold–Mariano** as the
   parametric cross-check (§1.2 metric stack).

2. **Win-rate vs. the best baseline.** `_win_rate_vs_best` (`forecasting/ledger.py:12340+`): the
   fraction of forecasts whose Brier is ≤ *every* baseline's Brier on the same question. This guards
   against an edge that is a mean artifact of a few large wins. **Acceptance: win-rate-vs-best > 0.5
   with its own CI clearing 0.5.**

3. **Complementarity via the simplex ensemble's `beats_both` gate.** `simplex_brier_weights`
   (`forecasting/market_ensemble.py:223-384`) fits the convex {market, agent} blend and reports
   `loo_ensemble_brier` (leave-one-out, the honest out-of-sample number) plus a seeded bootstrap CI on
   the weights. The `beats_both` flag is **True only when the LOO ensemble Brier is strictly below
   *every* per-source Brier** — never the optimistic in-sample number. **Acceptance: `beats_both ==
   True` and the agent weight's 95% CI excludes 0.** This is the cleanest single proof of orthogonal
   signal; it is exactly what returned weight 0.0 in the grounding study.

4. **Calibration, not just sharpness.** The agent must not buy a Brier win by miscalibrated
   over-confidence. We require a reliability curve / signed-calibration-error check
   (`signed_calibration_error`, `diagnose_hedging` in `forecasting/calibration_bias.py:206,449`) showing
   the gain is not driven by SCE drifting away from 0. **Acceptance: post-intervention |SCE| not worse
   than baseline, and the reliability curve stays near-diagonal.**

5. **The ForecastBench foreknowledge protocol is the substrate.** Every claim is made on resolved
   questions under the closed-book seal + model-cutoff gate + leak-domain denylist
   (`forecasting/forecastbench.py`, `forecasting/agent_protocol.py:230-270`), so a "win" cannot be
   leakage. Live confirmation rides MarketNightly (P2.1, task #179), which is foreknowledge-proof by
   construction (forecast *before* resolution).

6. **Pre-registration + ablation attribution.** Arms, n, and the decision rule are fixed *before*
   the run (this document). The 2×2 search-ablation harness (`forecasting/search_ablation.py`, P2.2,
   task #178) attributes any gain to the specific lever (search vs. judge vs. market-hidden) rather
   than to undifferentiated "agent goodness."

A result that clears (1)+(2)+(3) under (5), with (4) intact and (6) honoring the pre-registration, is
what we will call **provably step-function better**. "Step-function" specifically means the paired
edge is **materially larger than the −0.0039 we have today and on the correct side of zero** — our
target is a paired edge of **≥ +0.010 Brier** with the CI excluding 0 (rationale and power in §4.4).

### 1.3 Why the bar is honest about our current position

We are starting from **behind** (−0.0039) with **zero** measured complementarity. The bar above is
not a formality we expect to pass by default — the grounding study *failed* every one of (1)–(3) in
the market-visible configuration. The strategy below is the set of changes designed to flip them, and
§5 is candid about which are likely to move the number and which are speculative.

---

## 2. Levers → market-beating mechanisms

Each lever is stated as: **edge hypothesis** (why it should beat the market), **implementation**
(file-grounded, on our code), and **measurement** (how the §1.2 bar detects the gain). Levers are
ordered roughly by the causal chain (isolate → search → pool → calibrate → enforce).

### Lever A — Market isolation (the market-hidden arm). *The keystone.*

**Edge hypothesis.** The market beats us today because the agent *sees* the price and produces a noisy
copy of it; copies cannot be complementary to their original. If the agent reasons from the question
text + non-market evidence only, its errors de-correlate from the market's, which is the precondition
for the ensemble theorem to bite. Orthogonality is not a nice-to-have — it is the *only* thing that
can make the agent weight in the simplex non-zero. The grounding study's three null results (no
hedging to fix, no orthogonal signal, no ensemble lift) are all downstream of visibility; isolation is
the single change that can flip all three.

**Implementation.** The seam already exists: `_pre_cutoff_baselines` honors a `hidden_from_agent`
flag that withholds a baseline from the agent prompt while **still scoring it** as a
baseline_comparison (`forecasting/agent_protocol.py:249-270`); `build_forecastbench_case` exposes
`hide_market_baseline` (`forecasting/forecastbench.py:287-305, 402-403`). What is missing is *policy*:
it is a CLI flag, not the default for the intrinsic arm. Land task **#186** — run the closed-book
backtest with `hidden_from_agent=True` on the market baseline, so the agent forecasts intrinsically
and the market is still scored for the head-to-head and the simplex pool. Critically, isolation must
also extend to *evidence*: the context packet (`forecasting/protocol.py:294-548`) and related-forecast
context must not smuggle the price back in.

**Measurement.** Run the simplex ensemble (`simplex_brier_weights`) on the intrinsic-arm triples
`(market_p, agent_intrinsic_p, outcome)`. The decisive read is whether the agent weight's 95% CI now
**excludes 0** and `beats_both` flips to True — i.e. whether the independently-reasoned agent adds
signal the market lacks. Compare the intrinsic-arm paired edge and ensemble LOO Brier head-to-head
against the market-visible arm from the grounding study (same questions). This is the cleanest A/B in
the whole program: one flag, two arms, the §1.2 bar applied to each.

### Lever B — Supervisor fresh-search loop (evidence the market hasn't priced). *The largest single lift.*

**Edge hypothesis.** A market price is a snapshot of information aggregated *up to the freeze*.
On slow-moving or thin questions, relevant evidence exists at forecast time that the market has not
yet absorbed (low liquidity ⇒ slow incorporation). If our judge can name the unresolved crux and a
search tool can fetch evidence bearing on it, the agent updates on information the market is *missing*,
not merely re-weighting information both already have. This is the one mechanism that adds genuinely
*new* information to the system rather than re-processing the existing set — hence the largest
expected lift (the AIA P1.1 ablation claims ≈ 0.02 Brier).

**Implementation.** The loop is fully built but dormant. `run_quorum` accepts a `search_runner`
callable and a `max_research_rounds` bound; when the judge flags `information_gap` and supplies
`clarifying_queries`, `should_research` (`forecasting/quorum.py:646-668`) gates a fresh-search
re-synthesis (`quorum.py:823-848`). The default `search_runner=None` makes the path byte-identical to
no search (`research_rounds` stays 0). The gap: `quorum_jobs.py:195-209` never passes a runner. Land
task **#181** — implement a `search_runner` that takes `judge.clarifying_queries` and returns
`[{title, summary, source_url, available_at, ...}]` (wire the existing `news_search.py` /
`source_search.py` adapters), pass it into `run_quorum`, and **enforce time-travel admissibility**:
every fetched item must pass the `available_at <= cutoff` + leak-domain denylist filter
(`forecasting/agent_protocol.py:230-246`) so a backtest search cannot pull post-resolution evidence.

**Measurement.** The 2×2 search-ablation harness (`forecasting/search_ablation.py`, P2.2) classifies
each run by `research_rounds > 0` (search-ON vs OFF) crossed with judge-override ON/OFF, attributing
the paired Brier delta to search specifically. Run the paired bootstrap **within the search-ON cells**
vs the market: that isolates "evidence the market hadn't priced" as the source of the edge. Stratify
by horizon and liquidity (§3) — the hypothesis predicts the search lift concentrates in long-horizon /
illiquid questions.

### Lever C — Agent+market ensemble (pool the orthogonal signals). *The proof surface.*

**Edge hypothesis.** Two forecasts with independent error pool to a lower-variance, lower-Brier
estimate than either alone — the classic result the AIA paper restates (LLM 0.126 / market 0.111 /
ensemble 0.106). The blend is the *mechanism by which* Levers A and B convert into a market-beating
number: isolation makes the agent's error independent; search makes it informative; the log-odds pool
harvests both. We deliberately do **not** Platt/extremize the blend — stacking recalibration on the
convex blend erases its edge (`forecasting/market_ensemble.py:14-15`).

**Implementation.** Today the live forecast number ignores the fitted weight;
`fitted_market_advisory_weight` and `collect_market_llm_triples`
(`forecasting/market_ensemble.py:390+, 507+`) are analysis-only. Promote the fit to a *gated* live
weight: a scheduled job (cron) re-runs `collect_market_llm_triples` + `simplex_brier_weights` on the
rolling resolved set and ships the fitted convex weight into the live pool **only when the strict gate
passes** (`n >= DEFAULT_MIN_SAMPLE=30`, `beats_both == True`, agent-weight CI excludes 0). When the
gate fails, keep the prior weight — missing gate = no change, never a silent reweight. This makes the
ensemble weight adaptive and *self-disabling* when complementarity is not statistically real.

**Measurement.** `beats_both` on the LOO ensemble Brier **is** acceptance criterion (3). The bootstrap
weight CI is the significance test. Because the gate is LOO + CI-guarded, a positive result here is by
construction not in-sample overfitting.

### Lever D — Calibration / extremization (recover hedging the *intrinsic* agent introduces).

**Edge hypothesis.** *Conditional and secondary.* An independently-reasoned agent (Lever A) may hedge
toward 0.5 where the market-anchored agent did not — isolation removes the market's sharpness. If the
intrinsic arm's `diagnose_hedging` reports `center_ward_hedge=True` (high central mass **and** SCE < 0),
then base-rate-anchored extremization recovers Brier by sharpening *away from the reference-class base
rate*, not from 0.5. On the 899-question Metaculus panel the base-rate-anchored form beat every
0.5-anchored method (`platt_scale_anchored`, `forecasting/bayes_toolkit.py:353-380`). This lever does
**not** beat the market on its own; it repairs a side-effect of Lever A.

**Implementation.** Two wires, both opt-in and gated by the *measured* hedging diagnosis:
(i) activate mechanical calibration lessons (`enable_mechanical=True`) so a center-heavy + under-confident
scope emits a `logit_scale > 1` adjustment (`forecasting/calibration_bias.py`, applied at
`forecasting/learning.py:108-116`); (ii) thread the reference-class base rate into the apply path so
`learning.py:114` can call `platt_scale_anchored(p, base_rate, alpha=logit_scale)` instead of the
0.5-anchored `platt_scale`. **Both stay OFF until the intrinsic arm's LOO alpha sweep
(`sweep_platt_alpha`, `forecasting/backtesting.py:52-160`) shows α>1 lowers LOO Brier** — exactly the
empirical gate that (correctly) kept α=1 in the grounding study, where the agent did *not* hedge.

**Measurement.** Re-run `sweep_platt_alpha` and `diagnose_hedging` on the **intrinsic** arm. If
`best_alpha > 1` with `loo_brier < identity_brier`, activate at that α and re-score; the gain shows up
in the paired edge. If `best_alpha == 1` (as in the market-visible arm), do nothing — this lever is
inert by design when there is no hedging to fix.

### Lever E — Hooks: enforce orthogonality, don't merely permit it.

**Edge hypothesis.** Today the hooks enforce *input saturation* (evidence count, citations, components)
but not *output orthogonality*: a forecast can pass every gate while being a silent market echo. If we
*require* the reasoning that generates orthogonal signal — outside-view-first ordering, a named
disconfirmation scenario, an explored information frontier — and *detect* silent anchoring (final
number inside the market's vigorish), the harness can no longer "pass" by copying the market. Hooks
convert the strategy from advisory to enforced, which is the difference between a one-off study and a
durable edge.

**Implementation (file-grounded, on `forecasting/hooks/`):**
- `reasoning_sequence` hook: flag when `outside_view`/`base_rate` appear *after* `inside_view` in the
  reasoning-methods list — the current `_check_reasoning_composition`
  (`forecasting/hooks/builtins.py:413-431`) checks set membership and count, never order.
- `market_anchor` hook (only meaningful in the market-visible arm): WARN when the agent's final
  probability sits within ±5pp of the de-vigged market, forcing "reconcile or exceed" — either an
  explicit decomposition of *why* the components beat the market, or a sharpness floor if accepting it.
- `pre_mortem_discipline` hook: require a populated `disconfirmation_scenario` field when `pre_mortem`
  is claimed (output-validated, not name-only).
- `information_frontier_explored` hook: when a panel ran, require either a judge-flagged
  `information_gap` + a clarifying query (the search seam fired) or an explicit "no unresolved gaps"
  metadata record.
- Domain-aware thresholds in `forecasting/hooks/thresholds.py` (e.g. higher `min_perspectives` for
  election/tail-risk questions) — today all domains share one profile.

**Measurement.** Hooks do not directly produce Brier; they *gate* the behaviors the other levers
need. Measure indirectly: with the orthogonality hooks ON, the fraction of forecasts inside the market
vigorish should fall, and the simplex agent weight (Lever C) should rise. The hooks' value is *holding*
the edge once A–C produce it, and preventing regression to market-echo.

### Lever F — Learning / lessons: close the loop *before* commit, not after.

**Edge hypothesis.** *Defensive, not offensive.* Lessons currently apply a numeric nudge **after** the
agent's reasoning is locked (`forecasting/learning.py:37-120`) — a confirmation-bias trap: the
reasoning is already sunk. They cannot beat the market; at best they trim a systematic bias the next
cycle. Their honest role is to prevent the *intrinsic* agent from re-committing a measured per-domain
bias (e.g. "politics ran 8pp under-confident") by surfacing it as a re-reasoning trigger before the
probability locks, and to enforce structural rigor (reference class required, machine-scoreable output,
tail not compressed) via the compiled `lesson:*` hook rules.

**Implementation.** Inject active lessons as a **triggering question** into the agent context *before*
the final number is bound (not as post-commit text), and bind the re-consideration into the update
action. Keep the numeric `logit_scale` nudge as a backstop, gated on the same SCE significance as
Lever D. This is wiring already-present machinery (`active_lessons_for_question`,
`apply_active_lesson_adjustments`) one step earlier in the loop.

**Measurement.** Per-domain SCE trajectory over cycles (does the intrinsic agent's measured bias shrink
after lessons enter the reasoning loop?). This is a *calibration* metric (criterion 4), not a
market-beating one — included for completeness and honesty about its ceiling.

---

## 3. Where the market is weak — target question classes

The ensemble theorem bites hardest where the agent's orthogonal signal is largest, which is precisely
where the market is *thin, slow, or structurally mispriced*. We will stratify every result by these
classes and expect the edge to concentrate, not spread evenly.

| Class | Why the market is weak | Why our agent can add signal | Lever leverage |
|---|---|---|---|
| **Long-horizon** (resolution ≫ freeze) | Few informed traders commit capital far out; price decays toward priors; slow to update | Structured decomposition + base-rate anchoring on a reference class the thin market never prices | A (isolation), D (base-rate anchor), B (search) |
| **Illiquid / thin** (low volume, wide spread) | Large vigorish; price moves on noise, not information; stale | Fresh evidence is *un-priced* here by definition; de-vigging removes the overround | **B (search) — highest**, C (pool) |
| **Novel / no clean reference class** | Market has no analogues to anchor; herding on the first number | Agent constructs a reference class explicitly; red-team surfaces what the herd missed | A, E (red-team), B |
| **Dataset / numeric** (level/quantity, not a clean binary) | Market freeze value is a raw level, resolution often fractional — markets price these badly | Numeric decomposition + distributional reasoning the binary market cannot express | A, D (anchored extremization on the distribution) |

The grounding study deliberately *excluded* dataset/numeric sources to avoid fabricating ground truth
(`forecastbench.py` keeps only the four clean market-probability sources), so the dataset/numeric class
is a **future substrate** requiring a distributional scoring rule (CRPS), not Brier. The
**illiquid + long-horizon** intersection is the fishing hole for the first demonstration, because it is
where Lever B (the largest lift) and Lever A (the precondition) compound.

---

## 4. Experimental protocol (pre-registered)

### 4.1 Substrate

Resolved ForecastBench market-probability questions (manifold / metaculus / polymarket / infer),
closed-book seal, model-cutoff gate (resolution strictly after the model cutoff, 0
`model_cutoff_too_fresh`), leak-domain denylist, resolution-source URL withheld. Identical ingestion to
the grounding study (`forecasting/forecastbench.py`) so the new arms are directly comparable to the
existing 240/480-case baselines.

### 4.2 Arms (the agent forecaster varies; the market baseline is constant and always scored)

| Arm | Market visible? | Search loop? | Calib. | Purpose |
|---|---|---|---|---|
| **M0 — market baseline** | — | — | — | The opponent (de-vigged freeze price). Constant across arms. |
| **A0 — market-visible** (grounding study) | Yes | No | α=1 | The −0.0039 starting point; the control. |
| **A1 — intrinsic** (Lever A) | **No** | No | α=1 | Tests isolation alone: does an independent agent de-correlate? |
| **A2 — intrinsic + search** (A + B) | No | **Yes** | α=1 | Tests fresh evidence on top of isolation (expected largest lift). |
| **A3 — intrinsic + search + anchored-α** (A+B+D) | No | Yes | α* if hedging | Adds anchored extremization *only if* A2's sweep shows hedging. |
| **E1 — A2 + ensemble** (A+B+C) | both | Yes | α=1 | The headline: pool A2's agent with the de-vigged market; the `beats_both` test. |

A0 is reused from the grounding study (no re-run needed). A1/A2/A3 are new closed-book runs. E1 is an
*analysis* over A2's triples — no new forecasts, just `simplex_brier_weights`.

### 4.3 Pre-registered metrics and decision rule

For every arm vs M0 on the **same** questions (paired):
- **Primary:** `paired_agent_edge_mean_brier` with the seeded recenter-at-zero bootstrap p-value and
  95% CI (`forecasting/ledger.py:12269-12322`). **Decision: an arm "beats the market" iff its 95% CI
  excludes 0 on the agent side AND p < 0.05.**
- **Secondary:** `win_rate_vs_best` with CI clearing 0.5.
- **Ensemble (E1 only):** `simplex_brier_weights.beats_both == True` AND agent-weight 95% CI excludes 0.
- **Parametric cross-check:** HAC-robust **Diebold–Mariano** on the per-question loss differential
  (Newey-West variance; report alongside the bootstrap, with the dependence structure named).
- **Edge localization:** the **Murphy decomposition** (`BS = Uncertainty − Resolution + Reliability`,
  with a variance estimate) — the BSS gain **must live in the Resolution term**, else a referee
  replicates it by recalibrating the market. A Reliability-only gain does **not** count as beating the
  market.
- **Calibration guard:** `signed_calibration_error` / `diagnose_hedging` — |SCE| not worse than A0;
  reliability curve near-diagonal; plus the **Mincer–Zarnowitz** joint Wald test (α=0, β=1).
- **Instantaneous skill gate (leakage-immune):** Paleka consistency-arbitrage checks
  (Negation/Paraphrase/Consequence) on the panel — run **before** resolution as an early, contamination-
  proof read on whether the arm has real skill.
- **Attribution:** the 2×2 search-ablation (`forecasting/search_ablation.py`) confirms A2's marginal
  gain over A1 lives in the search-ON cells (mirrors AIA's search-ablation that attributes the lift to
  search, and guards against the ~42% of "search gain" that is really the leaked price).
- **Stratification:** all of the above, broken out by the §3 classes (horizon bucket × liquidity
  bucket), pre-registered to defeat the question-selection-bias objection.

The program is declared a **step-function success** iff **E1** (or **A2**) clears the primary +
secondary + ensemble criteria with the calibration guard intact, at a paired edge **≥ +0.010 Brier**.

### 4.4 Sample size and power

The grounding-study paired Brier deltas had a per-question standard deviation of roughly σ_δ ≈ 0.10–0.15
(typical for Brier deltas on this difficulty mix). For a one-sample paired test at α=0.05 (two-sided),
power 0.80:

- n ≈ (1.96 + 0.84)² · (σ_δ / target_edge)². With σ_δ = 0.12 and target_edge = 0.010, n ≈ 7.8 · 144 ≈
  **1,100 paired questions** to detect a +0.010 edge — large, because a 0.010 edge is small relative to
  per-question Brier noise.
- For a +0.020 edge (the size the P1.1 search ablation claims), n ≈ 7.8 · 36 ≈ **280 paired questions**
  — within reach of one expanded ForecastBench pull (the grounding study already had 240).

**Implication for the plan:** the *intrinsic-only* arm (A1) may show a real but sub-0.010 edge that we
are **underpowered** to certify on 240 cases — we must either expand n toward ~1,000 or rely on the
**search arm (A2/A3)**, whose larger expected effect is detectable at n ≈ 280–400. We therefore
prioritize the search loop not only for its larger point estimate but because it is the only lever whose
effect is *powered* at our realistic sample size. The simplex `beats_both` gate (E1) has its own n≥30
floor and a bootstrap CI, so it is testable far earlier than the full paired-edge certification — it is
the **early read** on whether the strategy is working at all.

### 4.5 Live confirmation

Any backtest win is confirmed forward on **MarketNightly** (P2.1, task #179): the agent forecasts live
*before* resolution, foreknowledge-proof by construction, accumulating paired deltas over weeks. A
backtest edge that does not replicate live is treated as a leakage or overfitting artifact, not a result.

---

## 5. Where the edge is thin (honest accounting)

We hold ourselves to the same skepticism the grounding study applied to extremization. The literature
both **supports** our mechanism and **warns** where it is fragile; we record both per lever.

**Where the literature SUPPORTS our thesis:** (i) the convex agent+market pool beating the market-alone
is the AIA Forecaster's central positive result (0.106 < 0.111), and "silicon crowd" shows mechanical
pooling beats the model's self-update — Levers A→C are the right architecture. (ii) Pooling in log-odds
is the externally-Bayesian, KL-optimal operator (Satopää) and is itself mildly extremizing — our
ensemble space is correct. (iii) ~50% of the super-vs-regular gap is **noise reduction** (BIN), which is
exactly what determinism + seeded bootstraps + ~10-agent ensembling deliver. (iv) The search loop is the
dominant accuracy lever (AIA) and reacting fast to news beats a consensus that lags (the 3%-drive-price
finding) — Lever B is the largest justified lift.

**Where the literature WARNS the edge is fragile:** (i) against a liquid, de-vigged market the standalone
agent **loses ~13bps** (AIA) and ~42% of "discovered" search signal is already in the price — so a
high agent weight on a liquid market is a **red flag**, not a win. (ii) Extremizing can actively **hurt**
if mis-set (Metaculus: 2.5 hurt, 1.5 helped) — Lever D must be fit, not assumed. (iii) The
**accuracy–correlation effect** means our panel can silently collapse into market-and-self agreement
(monoculture), erasing the orthogonal signal the whole thesis needs — diversity must be *measured*. (iv)
The profit edge "lives entirely on persistent human irrationality," decays as markets mature, and dies
above ~$500 capital from slippage (Beyond Accuracy / PolyBench). (v) Most "beats market" claims are
**leakage artifacts** (Pitfalls) — until GATE 4 (#183) calibrates the leak-judge, every backtest edge is
suspect.

- **Isolation (A) might *lose* head-to-head.** Removing the market price removes a genuinely
  informative anchor. A1's *standalone* Brier may be **worse** than A0's — the market is a strong
  baseline and the agent gives up real information by not seeing it. **This is acceptable and expected:**
  A1's job is not to win head-to-head but to become *complementary* (non-zero simplex weight). The win
  comes from **E1's pool**, not A1 alone. If A1 is both worse head-to-head *and* adds no ensemble weight,
  the whole thesis is falsified — and we should say so.

- **Search (B) is the largest claim and the least proven in our system.** The ≈0.02 lift is from the
  AIA paper's ablation, not ours; our search arm cells are sparse until #181 lands. Search also risks
  **leakage** (a fetched source that post-dates the cutoff silently reveals the answer) — the
  admissibility filter must be airtight or the "edge" is contamination. We treat any unusually large
  search-arm gain as a leakage red flag until audited.

- **Calibration / extremization (D) is inert without hedging.** The grounding study already showed
  α=1 is optimal and √3 *hurts* when the agent doesn't hedge. D only helps if the *intrinsic* agent
  hedges, which we will not know until A1 runs. We are not assuming it does.

- **Lessons (F) cannot beat the market.** Post-hoc calibration trims our own bias; it does not add
  signal the market lacks. We include it for rigor and regression-prevention, not as a market-beating
  lever, and we say so plainly.

- **Power.** At 240 cases we can certify a ~0.02 edge but **not** a 0.010 edge. A null result on the
  intrinsic-only arm at this n is *inconclusive*, not negative. We will not over-claim from an
  underpowered arm.

- **Generalization.** Everything is on clean binary market-probability questions. The dataset/numeric
  class — where markets are weakest — needs a distributional scoring rule (CRPS) we have not yet wired,
  so the most promising hunting ground is also the least validated today.

The intellectually honest position: **the ensemble + search path is the credible route to a provable
edge; the calibration path is a finished, correctly-null result; and the keystone (isolation) is a
single unshipped flag (#186) whose outcome we genuinely do not yet know.** The value of this program is
that every one of these claims is falsifiable on machinery we already built.

---

## 6. Prioritization — expected Brier-skill-per-effort

| Rank | Lever / task | Effort | Expected paired-edge contribution | Why first |
|---|---|---|---|---|
| **1** | **A — market-hidden arm (#186)** | Low (a flag → a policy) | Enables all complementarity; could flip simplex weight 0.0 → >0 | The keystone precondition; cheapest high-leverage change; one A/B answers the central question |
| **2** | **B — supervisor search loop (#181)** | Medium (wire `search_runner` + admissibility) | Largest single lift (≈0.02 claimed); the only lever powered at our n | Adds *new* information; the only arm certifiable at 240–400 cases |
| **3** | **C — ensemble live-weight gate** | Low (analysis → gated cron) | The *proof surface*; converts A+B into a number | `beats_both` is the early read; self-disables when not real |
| **4** | **E — orthogonality hooks** | Medium (4 hooks + thresholds) | Holds the edge, prevents market-echo regression | Durability; only matters once A–C produce signal |
| **5** | **D — anchored extremization** | Low (2 wires, gated) | Conditional; 0 if intrinsic agent doesn't hedge | Inert until A1's sweep proves hedging |
| **6** | **F — lessons-in-the-loop** | Medium | Defensive; cannot beat market | Calibration hygiene, not edge |

**Critical path:** #186 → #181 → ensemble gate → certify on A2/E1 at n≈280–400 → live-confirm on
MarketNightly. Levers D/E/F are parallel hardening, gated on the empirical reads from the critical path.

---

## Appendix: file-grounded reference

- **Paired bootstrap (proof criterion 1):** `forecasting/ledger.py:12230-12322`
  (`_compute_paired_brier_stats`, `_paired_bootstrap`; recenter-at-zero, seeded, plus-one corrected).
- **Win-rate-vs-best (criterion 2):** `forecasting/ledger.py:12340+` (`_win_rate_vs_best`).
- **Simplex ensemble / `beats_both` (criterion 3):** `forecasting/market_ensemble.py:223-384`
  (`simplex_brier_weights`), `:390+` (`collect_market_llm_triples`), `:507+`
  (`fitted_market_advisory_weight`).
- **Calibration / hedging (criterion 4):** `forecasting/calibration_bias.py:206` (`signed_calibration_error`),
  `:449-534` (`diagnose_hedging`); `forecasting/bayes_toolkit.py:353-380` (`platt_scale_anchored`).
- **Alpha sweep (Lever D gate):** `forecasting/backtesting.py:52-160` (`sweep_platt_alpha`).
- **Market isolation (Lever A):** `forecasting/agent_protocol.py:249-270` (`_pre_cutoff_baselines`,
  `hidden_from_agent`); `forecasting/forecastbench.py:287-305, 402-403` (`hide_market_baseline`); task #186.
- **Search loop (Lever B):** `forecasting/quorum.py:646-668` (`should_research`), `:670-880`
  (`run_quorum`, `search_runner`, `_augment_context`); `forecasting/quorum_jobs.py:195-209` (the unpassed
  runner); `forecasting/search_ablation.py` (2×2 attribution); task #181.
- **Lesson application (Lever F):** `forecasting/learning.py:37-120` (`apply_active_lesson_adjustments`),
  `:136-165` (`active_lessons_for_question`).
- **Hooks (Lever E):** `forecasting/hooks/builtins.py:413-431` (`_check_reasoning_composition`),
  `forecasting/hooks/thresholds.py`, `forecasting/hooks/profiles.py`.
- **Empirical baseline:** [`forecastbench-grounding-study.md`](forecastbench-grounding-study.md)
  (240 cases: agent 0.1668 / market 0.1629 / edge −0.0039 / simplex agent weight 0.0).
