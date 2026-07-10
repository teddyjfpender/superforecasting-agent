# The Harness Gauntlet — 50 questions that exercise the engine to depth

**Date:** 2026-07-10 · **Status:** research / cohort design (pre-registration candidate)
**Branch:** `superforecasting-agent-snapshot`
**Companions:** [Harness Benchmarking Strategy](harness-benchmarking-strategy.md),
[BLF adoption map](blf-adoption-map.md), [Live Edge Study](live-edge-study.md),
[Superforecaster Gates plan](../plans/2026-07-08-superforecaster-gates.md)

All markets, prices, polls, and data-series states below were verified live on
**2026-07-10** via web search. Prices move; the anchor to freeze is the one captured at
each question's forecast cutoff, per the baseline formalism in the benchmarking-strategy
memo (§7). Nothing here is hypothetical: every question is a currently-open uncertainty
with a named authoritative resolution path.

**Tranche 2 (N1–N25, §2b) added 2026-07-11.** The core 50 skews long — the cohort now
carries a deliberate fast arm: 15 questions resolving by 2026-10-15 and 10 more by
2026-12-01, so the engine's skill is *observable within the quarter* (score → postmortem
→ lesson-synthesis full loops before December). Tranche market states were verified live
on 2026-07-10, same discipline as above.

---

## 0. What "maximum exercise" means for this engine

The harness is not a probability generator; it is a lattice of subsystems, each of which
only runs when a question has the right *shape*. A gauntlet that proves the harness must
therefore be selected so that **every subsystem has questions that force it onto its hard
path** — not its happy path. The map:

| Subsystem (where it lives) | What actually exercises it | Question property required |
|---|---|---|
| Multi-provider quorum + belief trajectories + K-trials + Delphi rounds (`forecasting/quorum/` — `resolve_trial_count` K=3 on `impact=high`, `delphi_rounds`, per-step belief slots) | Genuine cross-model disagreement; evidence that arrives mid-trajectory; contested calls where trials diverge (the lone-skeptic effect) | `impact=high`, contested (market 25–75%), evidence-rich |
| Market anchors + blind→reconcile + deviation bets (`quorum.py` blind phase, `apply_market_anchor_discipline`, `ledger/deviation_bets.py` — **0 rows ever**; G8 `market_anchor_engaged`) | A liquid market the blind pool can disagree with by >10pp, forcing a named edge and a pre-registered deviation bet | Real Polymarket/Kalshi/Metaculus anchor, watched market source |
| Difficulty adjustment (`ledger/scoring.py` ABI-style, d=(p_market−y)²) | A spread of market-implied difficulty: near-50% markets AND lopsided ones | Anchor coverage across the price spectrum |
| Gate lattice (27 builtins + superforecaster gates G1–G8; `forecasting/hooks/builtins.py`, standard profile, live-origin only) | Payload shapes that historically passed-when-they-shouldn't: named tails on share boards (G1), missing per-candidate intervals (G2), anchor-less first commits (G3), round numbers (G4), stale cadence (G5), mis-summed boards (G6), crux-less high-impact (G7), unengaged markets (G8) | Vote-share distributions with novelty candidates; high-impact binaries; deliberately long-horizon questions |
| Deterministic specialists (`forecasting/specialists.py` — climatology KNN / seasonal-naive / living-model; seats **only** on numeric/distribution questions carrying a `metadata['series']` hint `{provider, symbol, unit}` over the wired data plane: `fred`, `bls`, `bea`, `coingecko`, `frankfurter`, `stooq`, `yahoo`; declines honestly otherwise) | Continuous questions where the climatology IS the right answer (LLM must beat it) and ones where it is NOT (regime break; LLM must out-argue it); plus series the plane cannot fetch (the decline path) | Economic prints with FRED/BLS hints; market levels with stooq/coingecko hints; NOAA/USGS counts with **no** wired provider (decline honesty) |
| CRPS scoring for distributions (`ledger/scoring.py`, `_vote_share_vector_score`) | Committed quantile/PMF payloads graded against realized values | Continuous + vote-share questions with tight resolution values |
| Watched sources + evidence refresh + triage (`ledger/watches.py`, `ledger/refresh.py`, `label_scoring.py` three-way relevance labels + contested routing + 80% trust gate) | High-velocity news flow that floods the triage queue with relevant/irrelevant/contested items | Fast-moving, evidence-rich questions with multiple watched feeds |
| Theses + correlation-honest event bands (`ledger/theses.py`, `set_thesis_correlation`, `p_ci90`/`p_sd` bands) | Clusters of member questions whose outcomes are genuinely correlated — where naive independent aggregation would lie | 3–6 member questions per thesis sharing a driver |
| Cadence + update discipline + VOI (`ledger/reviews.py` weekly default + deadline clamp, G5 `update_cadence_honored`, VOI staleness weight 0.55) | Long-horizon questions that punish set-and-forget; short-fuse ones that reward it | Multi-month/multi-year horizons alongside 2-week sprints |
| Resolution → auto-postmortem → lesson synthesis (`ledger/resolutions.py`, `lesson_templates.py`, compiled `lesson:*` hooks) | A steady stream of resolutions inside the observation window, including misses | ≥10 questions resolving within ~1 month of onboarding |
| Criteria-tightness discipline (admission formalism, benchmarking memo §4) | Questions whose resolution wording is itself contested | A few deliberately adversarial resolution criteria |

Two design constraints fall directly out of the code and must be honored at onboarding:

1. **Every question is committed `forecast_origin=live`** (agent `update_forecast` path,
   `enforce_resolved_hooks=True`). The exploratory origin bypasses the entire gate
   lattice by design — a gauntlet run through it proves nothing.
2. **Continuous questions must carry their `metadata['series']` hint at creation**
   (e.g. `{provider: "fred", symbol: "CPIAUCSL"}`), or the specialists never seat and
   the specialist-vs-LLM comparison silently vanishes. Questions on NOAA/NSIDC/USGS
   series (no wired provider) are *deliberately included* to prove the decline path —
   the specialist must raise `SpecialistDeclined`, never fabricate.

## 1. Selection matrix and composition

**Hardness bar:** market price in 25–75% where a market exists (verified 2026-07-10), or
documented expert disagreement; no question resolvable by a single lookup; preference for
questions where the outside-view base rate and the inside view point in different
directions — the superforecaster discriminator.

| Axis | Target | Delivered (core 50) | Tranche 2 (N1–N25) → cohort of 75 |
|---|---|---|---|
| Binary | ~20 | 20 (B1–B20) | +12 (N1, N3, N7–N10, N16, N17, N19, N21, N23, N25) → 32 |
| Categorical / vote-share distribution | ~10 | 10 (V1–V10) | +3 (N2, N4, N14) → 13 |
| Continuous / count | ~10 | 10 (C1–C10) | +10 (N5, N6, N11–N13, N15, N18, N20, N22, N24) → 20 |
| Thesis clusters | ~5 | 5 (T1–T5, aggregating members drawn from the 45) | +0 new; tranche members tag into T1 (N5, N8, N15, N17, N18), T2 (N4, N16, N21), T4 (N13, N20), T5 (N10, N24) |
| Long-horizon (deliberate, cadence-stressing) | ~5 | 5 (L1–L5) | +0 — the tranche is the fast arm by design |
| Liquid market anchor (named venue + slug/ticker, verified 2026-07-10) | ≥25 | ~41 (all B except B1; all V; C1–C6, C9, C10; every thesis via members; L1/L2/L4/L5) | +17 (N1–N5, N7–N11, N15, N17–N19, N21, N23, N24) → ~58 |
| Structured data feed (FRED/BLS/BEA/EIA/NOAA/NSIDC/USGS/CDC/GISTEMP) | ≥10 | 13 (C1–C10, B20, + core-PCE & ONI in T1/T4) | +10 (seats: N5, N11, N12, N15, N18 — incl. the plane's **first coingecko and frankfurter exercises**; declines: N6, N13, N20, N22, N24) → 23 |
| Evidence-rich fast movers (triage/refresh load) | ≥10 | 14 (B6, B10–B12, B14, B15, B18, C8, V1, V7, V9, B3/B4, T3) | +9 (N1–N3, N8, N10, N19, N22, N23, N25) → 23 |
| Adversarial resolution criteria | 3–5 | 8 flagged ⚠ (B2, B5, B6, B11, B12, B18, L2, L3) | +5 ⚠ (N2, N3, N16, N23, N25) → 13 |
| Resolves ≤1 month (by ~2026-08-10) | ~10 | 10 (B1, B2, B3, C1, C2, C3, V7, V9, V10, + gedatolisib fast) | +4 by 2026-08-11 (N1–N4) → 14 |
| Resolves ≤3 months (by ~2026-10-10) | ~20 | ~20 (B6, B18, V1–V6, C5, C6, + the ≤1-mo set rolls in) | +15 by 2026-10-15 (Window A, N1–N15) → ~35 |
| **Tranche 2 Window B: resolves 2026-10-15 → 2026-12-01** | ~10 | — | 10 (N16–N25) |
| Resolves ≤12 months (by ~2027-07) | ~15 | ~15 (B4, B5, B7–B17, B19, B20, C4, C7–C10, V8, T-clusters) | tranche fully resolved by 2026-12-01 |
| Multi-year | ~5 | 5 (L1–L5) | — |

With Tranche 2 the cohort's resolution ladder becomes: ~14 resolved by mid-August, ~35
by 2026-10-15, ~50 by 2026-12-01 — the fast mass the observation plan's lesson loop
(§3) needs to complete full turns inside the quarter.

Domains: geopolitics/conflict, US midterms 2026 + international elections, central
banks/macro prints, AI/tech milestones, energy/climate/weather, markets/finance,
science/health, sports (4 across the cohort, deliberately — the WC 2026 window closes
2026-07-19, so N1/N2 are the last fast sports reps). Tranche 2 adds three non-Fed
central banks (ECB/BoE/BoJ), FX and crypto levels on the wired data plane, and two
Baltic/Balkan-adjacent electoral information environments.

---

## 2. The fifty questions

Legend: **⚠** = deliberately adversarial/contested resolution criteria (stresses the
criteria-tightness discipline). Prices in parentheses are the live observation on
2026-07-10 — the anchor to *freeze* is the one captured at each question's forecast
cutoff. "Exercises" names the subsystems the question is chosen to push onto its hard path.

### Binaries (B1–B20)

**B1. Will the FDA issue an approval action for gedatolisib (Celcuity) on or before its 2026-07-17 PDUFA date?** ⚠(action type)
- Type: binary. Resolves: FDA approval letter / Celcuity 8-K by ~2026-07-17 (HR+/HER2−, PIK3CA-wildtype advanced breast cancer). Adversarial edge: an approval-with-restrictions vs a CRL vs a delay are three different outcomes for one date.
- Dates: cutoff 2026-07-14, resolve ~2026-07-17. Horizon: **≤1 month**.
- Market: none liquid (biotech options only) — a deliberate *no-anchor* case: the specialist/market hooks stay dark, the evidence+reasoning arm carries the whole forecast.
- Exercises: evidence triage on a single dense catalyst; gate G3 first-commit anchor (a reference class of first-in-class PI3K/AKT/mTOR PDUFA outcomes must be built); fast resolution→postmortem.
- Hard: first-in-class multi-target inhibitor with a mixed benefit/tolerability profile; the base rate of on-time first-cycle approval conflicts with the specific tolerability signal.

**B2. Will an AI obtain an IMO gold medal in 2026 under the market's stated sources?** ⚠(source mismatch)
- Type: binary. Resolves: IMO Grand Challenge (formal/Lean) or AIMO per the market rules, by 2026-12-31; IMO 2026 is 2026-07-10–21, papers 2026-07-15/16. Adversarial: a 2025-style *informal* DeepMind/OpenAI gold may not satisfy the listed formal sources — the price reflects source-mismatch risk, not capability risk.
- Dates: catalyst 2026-07-15/16, resolve by 2026-12-31. Horizon: **≤1 month** (effectively).
- Market: Polymarket `ai-wins-imo-gold-medal-in-2026` (63%); Metaculus 6728 (~78%). The 15-point gap IS the criteria fight.
- Exercises: criteria-tightness gate; blind-reconcile against two disagreeing crowds; fast feedback.
- Hard: the discriminator is reading the resolution source, not modeling model capability — a classic "the question is not what it looks like" trap.

**B3. Will the FOMC raise the target range at the 2026-07-28/29 meeting?**
- Type: binary. Resolves: Fed implementation note, 2026-07-29 14:00 ET (range now 3.50–3.75%).
- Dates: resolve 2026-07-29. Horizon: **≤1 month**.
- Market: Kalshi `KXFEDDECISION-26JUL` (hike 13–15¢); Polymarket `fed-decision-in-july-181` (15% hike); CME FedWatch ~89% hold — venues disagree 11–16%.
- Exercises: market-anchor engagement (G8) + deviation bet on the tail; quorum K=3 (high-impact); member of thesis T1.
- Hard: a real ~15% first-hike tail in a new chair's first cycle; June CPI (Jul 14) lands days before — the outside view (Fed holds) vs the inside view (hawkish dot plot, 4.2% CPI).

**B4. Will the Fed raise rates at any 2026 FOMC meeting (by 2026-12-31)? — FLAGSHIP**
- Type: binary. Resolves: any upward target-range move in 2026 per Fed statements.
- Dates: resolve 2026-12-31 (last SEP meeting Dec 8–9). Horizon: **≤6 months**.
- Market: Kalshi `FEDHIKE-26DEC31` (**50–51¢ — a literal coin flip**).
- Exercises: the maximum-entropy binary — panel disagreement + shrinkage α should peak here; deviation-bet discipline where the market itself has no view; thesis T1 anchor.
- Hard: the Fed is split down the middle (median dot 3.8% implies a hike; doves point at +57k payrolls) — the single best pure-binary skill discriminator in the set.

**B5. Will the US enter a recession in 2026 (NBER, or two consecutive negative real-GDP quarters)?** ⚠(resolution lag)
- Type: binary. Resolves: NBER dating attributed to 2026, or the two-negative-quarters clause per venue rules. Adversarial: NBER dating lags ~1 year, so the near-term resolver is the GDP clause — the wording matters.
- Dates: resolve 2026-12-31 (clause) / later (NBER). Horizon: **≤12 months**.
- Market: Kalshi `KXRECSSNBER-26` (9–10¢); Polymarket `us-recession-by-end-of-2026` (~12.5%).
- Exercises: low-base-rate calibration (anti-extremization floor, BLF A7 clamp audit); thesis T1 member with strong negative correlation to the hike questions.
- Hard: stall-speed payrolls (+57k) and GDPNow 1.3% vs a 2.2% consensus and Sahm-rule slack — the inside view (stalling) fights a low unconditional base rate.

**B6. Will the US federal government be shut down on 2026-10-01 (FY2027 appropriations lapse)?** ⚠(what counts)
- Type: binary. Resolves: appropriations lapse / OPM shutdown status at 00:01 ET 2026-10-01 (partial lapses count; technical same-day lapses don't).
- Dates: resolve 2026-10-01. Horizon: **≤3 months**.
- Market: Polymarket `government-shutdown-by-october-1-20260610162414910` (~47%); Kalshi `KXSHUTDOWNBY-26DEC31` cross-check.
- Exercises: near-50% market-anchor + deviation bet; evidence triage on appropriations news flow; it endogenously threatens C-arm release dates (a cross-question dependency the desk should flag).
- Hard: election-year brinkmanship five weeks before the midterms — CR base rate vs the fresh 2025-26 shutdown precedent.

**B7. Who wins the 2026 Ohio Senate special (Husted R vs Sherrod Brown D)?**
- Type: binary. Resolves: AP/Fox/NBC consensus or state certification, 2026-11-03.
- Dates: resolve ~2026-11-04. Horizon: **≤4 months**.
- Market: Polymarket `ohio-senate-election-winner` (R 51¢ / D 49¢).
- Exercises: polls-vs-fundamentals conflict at its purest; thesis T2 member; market-anchor.
- Hard: literal coin flip — Brown's brand + a +8 Fox poll vs Ohio's R+8 presidential lean.

**B8. Who wins the 2026 Georgia Senate race (Ossoff D vs Mike Collins R)?**
- Type: binary. Resolves: AP/Fox/NBC consensus or certification (incl. runoff), 2026-11-03.
- Dates: resolve 2026-11-04 (or Jan runoff). Horizon: **≤4 months** (runoff tail longer).
- Market: Polymarket `georgia-senate-election-winner` (D 86.5¢) — sharpest ratings-vs-market divergence on the board (Cook rates it Toss-up).
- Exercises: the case where a liquid market (87%) and an expert rating (toss-up) openly disagree — blind-reconcile must pick a side and register the edge; thesis T2.
- Hard: only Democratic incumbent defending a Trump-won state; the market's confidence vs the rater's caution is the whole question.

**B9. Who wins the 2026 Maine Senate race (Collins R vs Platner D)?**
- Type: binary. Resolves: AP/Fox/NBC or certification incl. any RCV rounds, 2026-11-03.
- Dates: resolve 2026-11-04. Horizon: **≤4 months**.
- Market: Polymarket `maine-senate-election-winner` (D 63.5¢, hot: $326K last week).
- Exercises: incumbent-beats-her-polls base rate (Collins 2020: trailed all fall, won +9) vs a tied RCP average — outside-view/inside-view conflict; ranked-choice tail; thesis T2.
- Hard: the base rate (Collins overperforms) directly contradicts the current polling and the market.

**B10. Will Russia and Ukraine agree to a ceasefire by 2026-12-31?**
- Type: binary. Resolves: mutually agreed suspension of direct military engagement, officially announced or credible-reporting consensus.
- Dates: resolve 2026-12-31 (shorter Oct 31 rung available). Horizon: **≤6 months**.
- Market: Polymarket `russia-x-ukraine-ceasefire-agreement-by` (Dec 40.5%); Metaculus 41138 (~40%).
- Exercises: negotiation-momentum inside view vs a base rate of repeatedly-blown deadlines (every Jan–Jun 2026 rung resolved NO — a reference class the desk owns); watched-source triage on a high-velocity feed; thesis T3-adjacent.
- Hard: the inside view (talks advancing) fights a hard empirical base rate of failed ceasefire deadlines.

**B11. Will the US and Iran reach a final nuclear deal by 2026-12-31?** ⚠(final vs interim)
- Type: binary. Resolves: a written instrument mutually signed/adopted with ≥1 concrete measurable limit, identified as *the final deal* contemplated by the 2026-06-14 MOU. Adversarial: "final deal" vs "another interim memorandum" is a live definitional fight; the 60-day MOU window/oil-waivers expire ~2026-08-21.
- Dates: shorter rungs Aug 18/Sep 30; resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `us-iran-final-nuclear-deal-by-20260621201254412` (Dec 37.5%, Sep 19.5%, Aug 12.5%).
- Exercises: criteria-tightness gate; deviation bet across the rung ladder (a term structure the desk can arbitrage); thesis T3 member; fast-moving evidence.
- Hard: the criteria are strict enough that a headline "deal" can resolve NO — reading the instrument is the skill.

**B12. Will the Israel–Hamas ceasefire be cancelled by 2026-12-31?** ⚠(strongest criteria fight)
- Type: binary. Resolves: either side announces cancellation, or credible-reporting consensus that the ceasefire is "no longer in effect."
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `israel-x-hamas-ceasefire-cancelled-by-october-31` (Dec rung 22%; six earlier rungs resolved NO).
- Exercises: the sharpest adversarial-criteria test in the set — Israel conducts near-daily strikes *inside a formally standing ceasefire*, so "no longer in effect by consensus" is precisely where the criteria-tightness gate earns its keep; thesis T3.
- Hard: the facts on the ground and the resolution wording are in open tension — the forecast is a claim about how adjudicators read "cancelled," not about violence levels.

**B13. Will Sudan's RSF and SAF agree to a ceasefire by 2026-12-31?**
- Type: binary. Resolves: publicly announced, mutually agreed halt with an explicit dated commitment (humanitarian pauses don't count).
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `sudan-civil-war-ceasefire-by-december-31-2026` (30.5%, thin).
- Exercises: a thin-but-real market (down-tiered anchor, G8 records the price with a low-quality flag); Africa-conflict evidence coverage where the source base is sparse (triage on weak feeds); the cross-domain-underpricing market-failure category.
- Hard: Quad/US mediation optimism vs a three-year record of failed ceasefires; thin liquidity means the market may itself be mispriced — a chance for genuine edge.

**B14. Will China and Taiwan have a military clash before 2027?**
- Type: binary. Resolves: any use-of-force encounter (missiles/artillery/gunfire/damaging ram); China Coast Guard counts, Taiwan CGA does not; warning shots/transits excluded — semi-adversarial asymmetry.
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `china-x-taiwan-military-clash-before-2027` (7.1%); Metaculus 41139 attack/blockade-2026 (10%) — documented cross-platform disagreement.
- Exercises: low-base-rate tail calibration; the gray-zone-incident definitional edge; long-horizon sibling of L1.
- Hard: outside view (no clash in decades) vs inside view (rising gray-zone tempo); the coast-guard asymmetry makes incident classification contestable.

**B15. Will Benjamin Netanyahu cease to be PM of Israel by 2026-12-31?**
- Type: binary. Resolves: Netanyahu no longer holds the PM office on 2026-12-31 per Knesset record. Compound: requires losing AND fast government formation (election expected 2026-10-27, coalition talks run weeks-to-months).
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `netanyahu-out-before-2027` (~43.5%, $123M, +9pts on the week).
- Exercises: compound-event decomposition (the belief trajectory should show the two conjuncts moving separately); high-velocity evidence; thesis T3.
- Hard: near-50% on a conjunction of an uncertain election result and an uncertain coalition-formation speed — decomposing the conjunction is the edge.

**B16. Will a UK general election be called on or before 2027-06-30?**
- Type: binary. Resolves: a GE formally called per gov.uk / Electoral Commission by 2027-06-30 (a new PM, presumptively Burnham, faces a dash-vs-wait choice with Reform at 25%+).
- Dates: resolve 2027-06-30. Horizon: **≤12 months**.
- Market: Polymarket `uk-election-called-by` (Jun-2027 44%; Dec-2026 15%).
- Exercises: cadence/update discipline over a long horizon; the leadership-transition news feed (triage); market-anchor.
- Hard: no fixed trigger — a pure judgment call about a new PM's incentives with a genuinely split market.

**B17. Will OpenAI complete an IPO by 2026-12-31?**
- Type: binary. Resolves: OpenAI shares begin public trading by 2026-12-31 (SEC EDGAR / exchange). Confidential S-1 filed 2026-06-08; company publicly guided 2027.
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `openai-ipo-by` (Dec 18.5%); Kalshi `KXIPOOPENAI` "announced by Mar 2027" ~59%.
- Exercises: hype-vs-stated-plan discrimination (the company said 2027, the market prices 18.5% reversal); thesis T5 member; market-anchor.
- Hard: the stated corporate plan and the residual market probability disagree — pricing the reversal risk is the skill.

**B18. Will OpenAI release GPT-6 by 2026-09-30?** ⚠(successor naming)
- Type: binary. Resolves: a model named GPT-6 (or recognized successor to GPT-5; "GPT-5.5 or similar" excluded) publicly accessible. GPT-5.6 shipped 2026-07-09 — adversarial: what counts as "the successor" invites a naming fight.
- Dates: resolve 2026-09-30. Horizon: **≤3 months**.
- Market: Polymarket `gpt-6-released-by` (Sep 72%; Aug 43.5%; Dec 92.5%).
- Exercises: criteria-tightness; shipping-cadence base rate vs hype; thesis T5 anchor.
- Hard: does OpenAI double-release within a quarter, and would it be *named* GPT-6 — a joint capability-and-naming judgment.

**B19. Will Nvidia be the largest company by market cap at 2026-12-31?**
- Type: binary. Resolves: largest market cap at close 2026-12-31 (exchange prices / companiesmarketcap). NVDA ~$4.89T now; next earnings ~2026-11-18.
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Polymarket `largest-company-end-of-december-2026` (Nvidia ~69.5%).
- Exercises: market-anchor near the 70% boundary; finance thesis-adjacent; a single-earnings-flip hazard the belief trajectory should track.
- Hard: ~70% is close enough to the boundary that one earnings miss flips it — calibrating the "stays #1" probability against megacap volatility.

**B20. Will 2026 be the warmest year on record in NASA GISTEMP?**
- Type: binary. Resolves: NASA GISTEMP LOTI annual anomaly, Jan-2027 release; 2026 YTD is 3rd-warmest (+1.14°C).
- Dates: resolve ~2027-01. Horizon: **≤7 months** (data feed).
- Market: Kalshi `KXGTEMP-26` (~23¢); Polymarket `where-will-2026-rank-among-the-hottest-years-on-record` (2nd 66¢ / 1st 25¢).
- Series: **GISTEMP LOTI** (`data.giss.nasa.gov`) — no wired provider → specialist **declines** (decline-honesty test).
- Exercises: structured-data question with a *deliberate specialist decline*; strong-El-Niño thesis T4 member (anti-correlated with the Atlantic-storm members — the correlation-honesty stress).
- Hard: El Niño peaks too late in the calendar to fully load 2026 (heat lands in 2027); the path to #1 needs record H2 months — Hansen vs Carbon Brief openly split.

### Categorical / vote-share distributions (V1–V10)

**V1. Who wins the 2026 Brazilian presidential election?**
- Type: categorical. Resolves: TSE-certified winner (runoff 2026-10-25 if needed).
- Dates: first round 2026-10-04, resolve ~2026-11. Horizon: **≤4 months**.
- Market: Polymarket `brazil-presidential-election` (Lula ~54%, Flávio ~23–26%); Kalshi `kxbrpres-26` (Lula 64%, Flávio 26%) — a **10-point cross-venue divergence** on one event.
- Exercises: categorical tail base rates (G1 on the field); blind-reconcile across two disagreeing venues; the Flávio-ineligibility legal wildcard as a live crux (G7).
- Hard: challenger's candidacy legally unresolved (ineligible 2026-06-16, appeal pending) yet he polls 32–37% — a category-defining structural uncertainty.

**V2. What first-round vote share will Lula receive (valid votes)?**
- Type: vote-share distribution. Resolves: TSE first-round valid-vote %, 2026-10-04/05.
- Dates: resolve 2026-10-05. Horizon: **≤3 months**.
- Market: companion Polymarket `...first-round-margin-of-victory` (bucketed) + `will-any-presidential-candidate-win-outright-in-the-first-round...` (15% >50%).
- Exercises: **per-candidate intervals (G2)** + CRPS on the committed share; the >50% outright tail (a named, live tail base rate); pollster-spread reasoning (Ideia 40.4 vs AtlasIntel 46.3).
- Hard: a ~6-point pollster spread and a live outright-win tail — the interval must be honestly wide, and the tail anchored.

**V3. Which party finishes second by vote share in the 2026 Swedish general election?**
- Type: categorical. Resolves: Valmyndigheten final count, ~2026-09-16.
- Dates: election 2026-09-13. Horizon: **≤3 months**.
- Market: Polymarket `sweden-parliamentary-election-2nd-place` (SD 53% / M 31%).
- Exercises: categorical with house-effect reasoning; M historically outperforms late polls (a base-rate crux); thesis-adjacent to V4.
- Hard: SD 19–20% vs M 16–18% is inside house-effect range — the second-place call is genuinely open.

**V4. What vote share will each Swedish party receive (S, SD, M, V, MP, C, KD, L)?**
- Type: multi-party vote-share distribution. Resolves: Valmyndigheten final count, ~2026-09-16.
- Dates: resolve 2026-09-16. Horizon: **≤3 months**.
- Market: no per-share market; anchored via V3 (2nd-place) + `sweden-parliamentary-election-winner` (S 96%) + `next-prime-minister-of-sweden` (Andersson 74%).
- Series/polling: PolitPro trend + June house polls.
- Exercises: the flagship **tail-base-rate + per-candidate-interval** case (G1+G2) — two parties (KD ~1.7–2.9%, L ~5.6–6.5%) straddle the 4% threshold and aggregators *disagree on which one is above it* (PolitPro shows the inversion), so per-party intervals must span the threshold; CRPS on the full vector.
- Hard: the 4% threshold is a discontinuity that flips seat math; the intervals on the two straddling parties are where naive point forecasts lie.

**V5. Who will be Israel's PM following the 26th Knesset election?**
- Type: categorical. Resolves: new PM sworn in per Knesset record (into H1 2027 if coalition talks run long).
- Dates: election expected 2026-10-27, resolve ~2026-Q4/2027-Q1. Horizon: **≤6–9 months**.
- Market: Polymarket `who-will-be-the-next-prime-minister-of-israel-after-the-next-election` (Eizenkot ~40%); Metaculus 38899 (Bennett 46%, Netanyahu 29%) — **different favorites on different platforms**.
- Exercises: categorical blind-reconcile where two crowds name different leaders; the Bennett–Lapid merger as a crux (G7); thesis T3.
- Hard: fragmented field, no bloc at 61 seats, and the crowds themselves disagree on the modal outcome.

**V6. How many Knesset seats will Likud win in the 2026 election?**
- Type: seat-count distribution. Resolves: CEC final allocation.
- Dates: election ~2026-10-27, resolve ~2026-Q4. Horizon: **≤6 months**.
- Market: Polymarket `israel-election-likud-of-seats` (20–24 and 25–29 buckets modal).
- Exercises: count/seat distribution + CRPS; per-bucket intervals sitting exactly on the polling range; thesis T3 member (Likud largest even as Netanyahu is blocked).
- Hard: bucket boundaries fall inside the polling range (22–24), so the distribution's shape, not its center, decides the score.

**V7. Who wins the 2026 FIFA World Cup?**
- Type: categorical. Resolves: winner of the 2026-07-19 final (FIFA official).
- Dates: resolve 2026-07-19. Horizon: **≤1 month** (fast, deep liquidity).
- Market: Polymarket `world-cup-winner` (France ~33–40%, Argentina ~18–20%, Spain ~17–19%, England ~16%); Kalshi `KXMENWORLDCUP-26` (France ~35–41%). ~$4.1B volume.
- Exercises: categorical calibration on a deep, liquid field (the sharpest anchor-quality case); fast resolution→postmortem; per-outcome tail base rates.
- Hard: a clear but sub-40% favorite in a wide-open final eight — a high-quality categorical calibration test with an unusually reliable market.

**V8. What will the 2026 midterm chamber outcome (balance of power) be?**
- Type: categorical (4-way). Resolves: AP/Fox/NBC consensus, 2026-11-03.
- Dates: resolve 2026-11-04. Horizon: **≤4 months**.
- Market: Polymarket `balance-of-power-2026-midterms` (D-sweep 43.5%, R-Senate+D-House 40.5%, R-sweep 14.5%, D-Senate+R-House 1.75%).
- Exercises: **joint/correlation reasoning** — the four outcomes are not independent of the House (B7–B9) and Senate races; the D-sweep price implies a Senate|House conditioning the desk must reproduce; thesis T2 capstone.
- Hard: two near-equal modal outcomes whose probabilities encode a correlation structure — getting the marginals right but the joint wrong fails here.

**V9. Who wins the 2026 Michigan Democratic Senate primary (2026-08-04)?**
- Type: categorical. Resolves: MI Democratic Party result / credible-reporting consensus.
- Dates: resolve 2026-08-04. Horizon: **≤1 month** (fast feedback).
- Market: Polymarket `michigan-democratic-senate-primary-winner` (El-Sayed 80% / Stevens 20%).
- Exercises: the starkest **polls-vs-market conflict** found — a post-McMorrow-exit poll shows Stevens 42 / El-Sayed 41, yet the market says 80/20; blind-reconcile must adjudicate poll vs momentum/endorsement signal; fast resolution.
- Hard: the market's confidence and the only public poll point in opposite directions — a direct test of which signal the desk trusts.

**V10. How many missile tests will North Korea conduct in July 2026?**
- Type: count/categorical. Resolves: ballistic/cruise/anti-ship tests in July 2026 (SAMs/MLRS excluded), ~2026-08-01.
- Dates: resolve 2026-08-01. Horizon: **≤1 month** (fast).
- Market: Polymarket `number-of-north-korea-missile-tests-in-july-2026-20260626154530205` (1 = 39.5%, 2 = 29.5%, 3+ = 18.1%; "<1" already closed).
- Exercises: a short-horizon **count distribution** where over- and under-extrapolation from the running pace both lose; PMF calibration; fast feedback.
- Hard: count distributions punish anchoring on the salient recent tempo — the shape of the low-count PMF is the skill.

### Continuous / count (C1–C10)

**C1. What headline YoY CPI will the BLS report for June 2026 (released 2026-07-14)?**
- Type: continuous (%). Resolves: BLS CPI-U NSA 12-month change, June release. Series: **FRED `CPIAUCSL`** (wired → specialist SEATS).
- Dates: resolve 2026-07-14. Horizon: **≤1 month** (4-day sharp CRPS test).
- Market: Kalshi `KXCPIYOY-26JUN` (implied ~3.75%; P(>3.8%)=30–34¢).
- Exercises: **climatology/seasonal-naive specialist vs LLM** on a FRED series (BLF A5); CRPS; thesis T1 member; market-anchor + deviation bet.
- Hard: the market expects a large 4.2→~3.75 one-month drop on energy base effects — the *magnitude* against sticky tariff-core is genuinely uncertain, and the specialist's seasonal read may beat or miss it.

**C2. What monthly change in nonfarm payrolls will the BLS report for July 2026 (released 2026-08-07)?**
- Type: continuous (thousands). Resolves: BLS Employment Situation, July, initial print. Series: **FRED `PAYEMS`** (MoM; wired → specialist SEATS).
- Dates: resolve 2026-08-07. Horizon: **≤1 month**.
- Market: Kalshi `KXPAYROLLS-26JUL` (implied median ~80–85k; P(>100k)=39–41¢).
- Exercises: specialist-vs-LLM CRPS; the market median (~80k) sits *above* June's +57k — a rebound-vs-stall deviation bet; thesis T1.
- Hard: persistent negative revisions and shrinking labor supply muddy the breakeven — the specialist's persistence forecast and the market's rebound disagree.

**C3. What advance-estimate annualized real GDP growth will the BEA report for Q2 2026 (released 2026-07-30)?**
- Type: continuous (% SAAR). Resolves: BEA advance estimate, first print. Series: **FRED `A191RL1Q225SBEA`** (wired → specialist SEATS).
- Dates: resolve 2026-07-30. Horizon: **≤1 month**.
- Market: Kalshi `KXGDP-26JUL30` (~2.0–2.1%) vs **Atlanta Fed GDPNow 1.3%** — a large model-vs-market wedge.
- Exercises: the regime-break case where the *LLM must out-argue the specialist and the market* (inventory/trade noise from tariff front-running); CRPS; thesis T1.
- Hard: a rare, explicit ~0.8pp GDPNow-vs-Kalshi gap — the forecast is a bet on which nowcast is right.

**C4. What will the 10-year Treasury constant-maturity yield be on 2026-12-31?**
- Type: continuous (%). Resolves: last 2026 `DGS10` value (H.15). Series: **FRED `DGS10`** / stooq (wired → specialist SEATS).
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Kalshi `KXNOTE10Y-26DEC31` (P(≥4.75%)=21–22¢); spot 4.54%.
- Exercises: continuous specialist (seasonal-naive on a daily series) vs LLM macro reasoning; a fat right tail to model (25% mass >4.75%); market-anchor.
- Hard: hike-risk repricing vs oil-detente disinflation pull the tails in opposite directions — a genuinely two-sided distribution.

**C5. How many named storms will the 2026 Atlantic hurricane season produce?**
- Type: count. Resolves: NHC operational naming, Jun 1–Nov 30 (final HURDAT2). Series: **NHC/HURDAT2** — no wired provider → specialist **DECLINES**.
- Dates: resolve 2026-12-01. Horizon: **≤5 months**.
- Market: Kalshi `KXTROPSTORM-26DEC01` (implied median ~11; P(>12)≈30¢).
- Exercises: the flagship **specialist-decline + climatology-conflict** case — market median 11 vs climatology 14.4 vs CSU 9, in a strong El Niño with only 1 storm by Jul 10; count CRPS; thesis T4 (anti-correlated with the warming members).
- Hard: three credible baselines (market/climo/model) disagree by ±3 storms, and the LLM must reason about El Niño suppression the seasonal-naive specialist cannot (it declines) — the discriminator is choosing among conflicting outside views.

**C6. How many major (Cat 3+) hurricanes will the 2026 Atlantic season produce?**
- Type: count. Resolves: NHC Cat-3+ count, same window. Series: **NHC** — specialist DECLINES.
- Dates: resolve 2026-12-01. Horizon: **≤5 months**.
- Market: Kalshi `KXHURCTOTMAJ-26DEC01` (P(>1)=61¢, P(>2)=33¢; CSU says 1, NOAA 1–3).
- Exercises: highest-variance tail of a suppressed season; count CRPS; thesis T4.
- Hard: majors are the fat-tailed subset — a suppressed mean with a heavy tail is exactly where point forecasts fail.

**C7. How many M7.0+ earthquakes will occur worldwide in 2026?**
- Type: count. Resolves: USGS ComCat query `minmagnitude=7`, catalog read at a fixed date (revision caveat). Series: **USGS ComCat** — no wired provider → specialist DECLINES.
- Dates: resolve ~2027-01. Horizon: **≤6 months**.
- Market: none — a pure structured-data question with no market anchor (the specialist-decline + no-anchor case).
- Exercises: **Poisson climatology as the honest baseline** (long-run mean ~14–15/yr; 8 YTD) that the LLM must not over-update away from on the salient June Venezuela doublet (~3,800 dead); count CRPS; the decline path.
- Hard: a textbook base-rate-vs-salience trap — the disciplined answer is close to Poisson(15), and the inside view (recent hot pace, vivid disaster) pulls the wrong way.

**C8. How many confirmed US measles cases will CDC report for 2026?**
- Type: count. Resolves: CDC 2026 year-end confirmed total (finalized early 2027). Series: **CDC measles data** — no wired provider → specialist DECLINES.
- Dates: resolve ~2027-01. Horizon: **≤6 months** (fast-moving evidence).
- Market: none — evidence+refresh carry it.
- Exercises: high-velocity **watched-source + refresh + triage** on CDC weekly updates (2,170 YTD by Jul 2, already near the full-2025 record); count CRPS; the year-end *bucket* is the uncertainty.
- Hard: the trajectory near-certainly sets a post-elimination record, but the year-end level (2,500 vs 3,000 vs 3,500+) depends on outbreak containment — a level question dressed as a foregone conclusion.

**C9. What will the December 2026 monthly-average Brent price be (EIA)?**
- Type: continuous ($/bbl). Resolves: EIA Europe Brent spot monthly average. Series: **FRED `DCOILBRENTEU`** (wired → specialist SEATS) / EIA STEO `BREPUUS`.
- Dates: resolve ~2027-01. Horizon: **≤6 months**.
- Market: Kalshi `KXWTIMAX-26DEC31` (WTI yearly-high proxy) as the nearest anchor; EIA July STEO Q4 = $70.
- Exercises: **regime-break where the specialist's history and the EIA baseline are both stale** — spot $79 (Jul 9), EIA cut Brent $13 in one month after the Hormuz MOU, then US strikes on Iran resumed this week; CRPS; the belief trajectory should show the price snapping to news.
- Hard: violently bimodal (MOU holds → $70; Iran re-escalation → spike) — a single distribution must carry two regimes.

**C10. What will the S&P 500 close at on 2026-12-31?**
- Type: continuous / distribution. Resolves: S&P DJI official close 2026-12-31, bucketed. Series: **FRED `SP500`** / stooq `^SPX` (wired → specialist SEATS). Spot 7,543.64 (Jul 9).
- Dates: resolve 2026-12-31. Horizon: **≤6 months**.
- Market: Kalshi `KXINXY` (yearly range) + `KXINXDIRY` (year-end direction).
- Exercises: continuous specialist (trend/seasonal) vs LLM macro-regime reasoning; a genuinely two-tailed year-end distribution (index at ATH, strategists split 7,100 bear vs bull); CRPS; market-anchor.
- Hard: at/near all-time highs with a hike-risk macro overhang — the distribution is bimodal and no single range dominates.

### Thesis clusters (T1–T5) — correlation-honest event bands

Each thesis is a `thesis`-type question aggregating its tagged member questions into a
health+score with a **correlation-honest** band (`set_thesis_correlation` pins pairwise ρ;
the aggregate `p_ci90`/`p_sd` widens vs the naive independent product). The members are
drawn from B/V/C above plus a few named satellites; the point is that naive independent
aggregation would misstate the band, and T4 deliberately contains **anti-correlated**
members to stress the sign handling.

**T1. US inflation-and-rates regime, 2026.**
- Members: B3 (July hike), B4 (any 2026 hike), C1/C2 (CPI/NFP prints) + Aug CPI (`KXCPIYOY-26AUG`) + core PCE June (FRED `PCEPILFE`, no market) + Fed-cut-count (Polymarket `how-many-fed-rate-cuts-in-2026`, 0 = 78%) + B5 (recession, negatively correlated).
- Correlation story: the inflation prints and the hike path are **strongly positively correlated** (a hot CPI lifts every hike member together); recession is **negatively** correlated with the hikes. Naive independence would badly understate the band.
- Exercises: correlation-honest event band with mixed signs; the joint-macro-state coherence the macro agent flagged (don't forecast marginals independently); cadence across a dense print calendar.

**T2. 2026 Democratic midterm wave.**
- Members: House control (`which-party-will-win-the-house-in-2026`, D 83.5¢), Senate control (`which-party-will-win-the-senate-in-2026`, R 54¢), GOP House-seat count (Kalshi `KXRHOUSESEATS-27`), Dem Senate-seat count (Kalshi `KXDSENATESEATS-27`), House PV margin (`2026-midterms-house-popular-vote-margin-of-victory-224`), V8 (balance of power), B7/B8/B9 (OH/GA/ME races).
- Correlation story: a national-environment shift moves **all** members together — the seat counts, the margin, and the individual races share the generic-ballot driver; independent aggregation would produce an absurdly tight band on "Democrats do well everywhere."
- Exercises: the strongest positive-correlation band; the seat-count distributions (CRPS) and the margin distribution feed the aggregate; VOI should rank the toss-up races (OH/GA) highest.

**T3. Middle East de-escalation, 2026.**
- Members: B11 (Iran deal), B12 (Gaza ceasefire cancelled — inverted), Hezbollah disarmament (Polymarket `will-hezbollah-disarm-by-march-31`, Dec rung 11.5%), B15 (Netanyahu out), V5 (Israel PM), V6 (Likud seats).
- Correlation story: regional shocks (an Iran breakdown, a Gaza collapse) correlate across members; the Israeli-politics members share a domestic driver — the band must reflect that a single shock moves several.
- Exercises: correlation-honest band on a fast-moving, adversarial-criteria-heavy cluster; heavy triage load (six high-velocity feeds).

**T4. Strong-El-Niño climate regime, 2026-27.**
- Members: C5 (named storms), C6 (major hurricanes) + hurricanes (Kalshi `KXHURCTOT-26DEC01`), B20 (2026 warmest year), July global heat record (Kalshi `KXHMONTH-26JUL`), super-El-Niño peak ONI ≥ +2.0 (CPC ONI, no market), Arctic Sept sea-ice extent (NSIDC / Metaculus 11545).
- Correlation story: **mixed-sign** — ENSO is the shared driver, but a strong El Niño *suppresses* Atlantic storms while *boosting* global temperature, so the storm members are **anti-correlated** with the warming members. The sharpest test of correlation-sign handling in the set.
- Exercises: correlation-honest band with anti-correlated members; the specialist-decline arm (NOAA/NSIDC/USGS series, no wired providers); CRPS across four continuous members.

**T5. Frontier-AI race, 2026.**
- Members: B18 (GPT-6 by Sep 30), Gemini 4 in 2026 (Manifold `gemini-4-released-in-2026`, 83%), best-model-at-year-end (Polymarket `which-company-has-best-ai-model-end-of-2026`, categorical), ARC-AGI-2 top score (Metaculus 41131, continuous), METR 50% time-horizon (Manifold `best-metr-time-horizons-in-2026`, continuous), B17 (OpenAI IPO).
- Correlation story: a shared capability-frontier driver links the release and benchmark members; the band should widen where a single lab's launch moves several members at once.
- Exercises: correlation-honest band spanning binary + categorical + continuous members; thin-market (Manifold) anchor handling; the benchmark-CRPS members.

### Long-horizon (L1–L5) — deliberate cadence and update-discipline stressors

**L1. Will China engage in a full-scale blockade of Taiwan before 2035?**
- Type: binary, multi-year. Resolves: Metaculus 12309 criteria by 2035-01-01.
- Market: Metaculus 12309 (~13%, low forecaster count).
- Exercises: **cadence/update discipline (G5) over years** — a set-and-forget question that the weekly sweep must keep alive; VOI staleness weighting; the anti-market-echo stance on a thin community prediction.
- Hard: classic outside-view (no blockade in 75+ years) vs inside-view (PLA capability curve, Davidson window) with published expert ranges 20–70%.

**L2. Will OpenAI announce it has attained AGI before 2030?** ⚠(self-declaration)
- Type: binary, multi-year. Resolves: Kalshi `OAIAGI-29` — *pure self-declaration* (OpenAI announces AGI by 2029-12-31); no capability test.
- Market: Kalshi `OAIAGI-29` (~40¢); `OAIAGI-26` (~7.4¢).
- Exercises: the criteria-tightness discipline at its most extreme — the resolver is a **corporate speech act** entangled with the Microsoft-contract AGI clause; long-horizon cadence.
- Hard: the forecast is about corporate/legal incentives to *declare*, not about capability — separating the two is the entire skill.

**L3. When will the first general AI system be devised, tested, and publicly announced?** ⚠(compound criteria)
- Type: date/continuous, multi-year. Resolves: Metaculus 5121 compound gate (adversarial Turing + robotic SAT + Atari/Montezuma).
- Market: Metaculus 5121 (community median ~Jan 2033; ~25% by 2029).
- Exercises: long-horizon CRPS on a date distribution; the compound-AND-gate means **capability arrival ≠ resolution** — pairs adversarially with L2's self-declaration; multi-year cadence.
- Hard: the AND-gate over four hard sub-criteria makes the resolution date lag capability by years — modeling the gate, not the frontier.

**L4. Who wins the 2027 French presidential election?**
- Type: categorical, ~21-month horizon. Resolves: Conseil constitutionnel proclamation, 2027-05.
- Market: Polymarket `next-french-presidential-election` (Bardella ~30%); RN-candidate market (`...national-rally-candidate`, Le Pen 93% after the 2026-07-07 partial reprieve).
- Exercises: long-horizon categorical cadence; a nested crux (who is even the RN candidate) that a linked sub-question (G7) tracks; the fragmented-field tail base rates (G1).
- Hard: 11+ declared candidates, a fragmented center, and the RN standard-bearer itself legally unsettled — a categorical whose *option set* may change.

**L5. Who wins Argentina's October 2027 presidential election?**
- Type: categorical, ~15-month horizon. Resolves: CNE/DINE official results, 2027-10-23.
- Market: Polymarket `argentina-presidential-election-winner` (Milei 50% / Kicillof 43%); companion `milei-out...before-2027` (7%).
- Exercises: long-horizon near-coin-flip categorical; cadence + update discipline conditioned on a slow-moving macro-stabilization driver; market-anchor.
- Hard: incumbent vs main Peronist is a near coin flip *conditional on economic stabilization holding 15 more months* — a long-horizon conditional the desk must keep re-forecasting.

---

## 2b. Tranche 2 — the near-horizon 25 (added 2026-07-11)

The core 50 proves depth; this tranche buys *feedback speed*. Fifteen questions resolve
by **2026-10-15** (Window A) and ten more by **2026-12-01** (Window B), so scoring,
postmortems, and lesson synthesis all complete inside the observation quarter. Same
hardness bar (contested 25–75% where a market exists, or documented expert disagreement;
outside-view-vs-inside-view conflicts preferred), same legend (⚠, prices observed live
**2026-07-10**, freeze at each cutoff), same onboarding constraints (live-origin;
`metadata['series']` hints at creation). Where a venue's dated instance had not yet
listed on 2026-07-10 (noted per question), the series is named and the price is captured
at cutoff — that capture is itself part of the snapshot discipline.

### Window A — resolves by 2026-10-15 (N1–N15)

**N1. Will France win its 2026-07-14 World Cup semifinal and reach the final?**
- Type: binary. Resolves: FIFA official result of SF1 (Dallas, 2026-07-14), France vs the Spain–Belgium QF winner; advancing on extra time or penalties counts.
- Dates: pairing fixed 2026-07-11, cutoff 2026-07-13, resolve 2026-07-14. Horizon: **days**.
- Market: Polymarket `world-cup-winner` (France ~33–40% tournament-wide) + Kalshi `KXMENWORLDCUP-26` (~35–41%); the per-match market lists once the pairing fixes Jul 11 — capture at cutoff.
- Exercises: the fastest resolution→postmortem turn in the cohort (days from commit to score); snapshot discipline on a fast-moving line; conditional-probability decomposition — the desk must back the implied SF-win probability out of the tournament boards and defend any deviation.
- Hard: France's 2-0-over-Morocco form vs a rested Spain is a genuine 55–65% zone call, and the implied-conditional arithmetic is exactly where sloppy desks contradict their own V7 commit.

**N2. Who wins the 2026 World Cup Golden Boot?** ⚠(tie-break criteria)
- Type: categorical. Resolves: FIFA official Golden Boot award after the 2026-07-19 final (tie-breaks: most assists, then fewest minutes).
- Dates: resolve 2026-07-19. Horizon: **≤2 weeks**.
- Market: Polymarket golden-boot board (Mbappé 43%, Messi 38%; $27M volume); Kalshi `KXWCGOALLEADER-26` (Messi 39% / Mbappé 36% as of Jun 23) — the two venues **disagree on the favorite**.
- Exercises: cross-venue blind-reconcile on a fast categorical; tail base rates on the chasing pack (Kane, Haaland); criteria-tightness — the award's assist/minutes tie-break makes "most goals" the wrong mental model.
- Hard: a two-to-three-match race where one brace flips the ordering, priced oppositely by two liquid crowds; resolution can hinge on the tie-break rule, not the scoring table.

**N3. Will OPEC+ announce a further production increase for September at its 2026-08-02 meeting?** ⚠(what counts as an increase)
- Type: binary. Resolves: official communiqué from the 2026-08-02 (virtual) meeting of the V7 producers announcing any headline production-cap increase for September; compensation-schedule adjustments alone don't count.
- Dates: resolve 2026-08-02. Horizon: **≤1 month**.
- Market: Polymarket `will-opec-hike-production-by-next-meeting` (live; thin — capture at cutoff); C9's EIA/Kalshi complex is the context anchor.
- Exercises: criteria-tightness on baseline-vs-compensation accounting (the classic OPEC gotcha); base rate (five consecutive monthly increases, +188 kb/d for August) vs inside view (US strikes on Iran resumed this week; the group says the pace "could be paused or reversed"); feeds C9's bimodal Brent distribution and T1's energy pass-through story.
- Hard: the unwind streak says yes; fresh Iran re-escalation and first-meeting-without-UAE group dynamics make the pause live — and "increase" itself requires reading the quota tables.

**N4. Who wins the 2026 Minnesota DFL Senate primary (2026-08-11)?**
- Type: categorical. Resolves: MN Secretary of State results / credible-reporting consensus, 2026-08-11 (open seat; Tina Smith retiring).
- Dates: resolve 2026-08-11. Horizon: **≤1 month**.
- Market: Polymarket `minnesota-democratic-senate-primary-winner` (Flanagan 79% / Craig 19%).
- Exercises: V9's sibling one week later — organization/endorsement signal (convention endorsement, Smith's backing) vs fundraising/moderate-lane signal (Craig's larger warchest, skipped the endorsement process); the V9+N4 pair gives a two-point primary-model calibration read inside a single week; T2-adjacent.
- Hard: the 79% price leans on exactly the signal (party infrastructure) that open primaries sometimes ignore; primary polling is sparse and convention-endorsement effects are regime-dependent in Minnesota.

**N5. What monthly change in nonfarm payrolls will the BLS report for August 2026 (released 2026-09-04)?**
- Type: continuous (thousands). Resolves: BLS Employment Situation, August, initial print. Series: **FRED `PAYEMS`** (MoM; wired → specialist SEATS).
- Dates: resolve 2026-09-04. Horizon: **≤2 months**.
- Market: Kalshi `KXPAYROLLS-26AUG` (monthly series; July instance live now — the August instance lists ~1 month out, capture at listing).
- Exercises: specialist-vs-LLM CRPS with a scheduled mid-trajectory evidence drop — the July print (C2, Aug 7) lands between commit and resolution, the cleanest belief-trajectory update test in the tranche; T1 member.
- Hard: stall-speed (+57k June) vs a falling labor-supply breakeven — a near-zero August and a rebound past 100k are both live, one month deeper into the stall than C2.

**N6. What will the August 2026 ISM Manufacturing PMI be (released 2026-09-01)?**
- Type: continuous (index). Resolves: ISM Manufacturing Report on Business, August, headline PMI. Series: **ISM (proprietary)** — no wired provider → specialist **DECLINES**.
- Dates: resolve 2026-09-01. Horizon: **≤2 months**.
- Market: none liquid named on 2026-07-10 (venue instances for monthly ISM appear sporadically — capture at cutoff if one lists).
- Exercises: the decline path on a *macro* series (the core 50 only declines on climate/geo/health series); diffusion-index reasoning — the 50.0 boundary is a narrative discontinuity but not a CRPS one, a trap for level-thinkers.
- Hard: six straight expansion months but decelerating (53.3 ← 54.0) with prices-paid still at 73 — late-cycle ISM momentum is where extrapolation and mean-reversion both routinely miss.

**N7. Will the ECB raise its key rates at the 2026-09-10 meeting?**
- Type: binary. Resolves: ECB monetary policy decision press release, 2026-09-10 14:15 CET; any ≥25bp increase in the deposit facility rate.
- Dates: resolve 2026-09-10. Horizon: **≤2 months**.
- Market: Polymarket monthly ECB series (`ecb-interest-rates-<month>-2026`; June/July instances verified live) + `ecb-rate-hike-in-2026`; OIS pricing ~**50%** for a September hike (Reuters, Jul 9).
- Exercises: a literal coin flip on a non-Fed central bank — does the macro reasoning generalize past the FOMC; the July 23 meeting (pause expected) is a scheduled mid-trajectory catalyst; N7/N8/N9 form a three-central-bank cluster whose correlation the desk must pin, not assume.
- Hard: the June hike was insurance against Middle-East energy pass-through; September turns on whether second-round effects show up in exactly two more core prints — the ECB itself says the call is contingent on oil.

**N8. Will the FOMC raise the target range at the 2026-09-15/16 meeting?**
- Type: binary. Resolves: Fed implementation note, 2026-09-16 14:00 ET.
- Dates: resolve 2026-09-16. Horizon: **≤2 months**.
- Market: Polymarket `fed-decision-in-september-762` (no change 56%, +25bp **38.5%**); Kalshi `KXFEDDECISION-26SEP`.
- Exercises: the specific-meeting slice of B4's coin flip — the desk must hold a coherent term structure across B3 (July ~15%), N8 (~38%), N17 (October) and B4 (any-2026 ~50%); the four prices over-determine each other, so cross-question coherence is directly auditable; quorum K=3; T1 member.
- Hard: 38.5% sits exactly where a first hike under a new chair either lands on the September SEP round or slips — July CPI (Aug 12) and Jackson Hole both hit mid-window.

**N9. Will the Bank of England raise Bank Rate at the 2026-09-17 meeting?**
- Type: binary. Resolves: BoE MPC announcement, 2026-09-17; any increase from the prevailing Bank Rate (3.75%; June vote 7–2 to hold).
- Dates: resolve 2026-09-17. Horizon: **≤2 months**.
- Market: Polymarket `bank-of-england-decision-in-september` (live; capture at cutoff) + `bank-of-england-rate-hike-in-2026`.
- Exercises: documented professional disagreement as the anchor-of-record — Bank of America (hikes in July *and* September) vs Oxford Economics (hold into 2027); the July 30 MPC is the mid-trajectory catalyst; third leg of the N7/N8/N9 correlation cluster.
- Hard: a 7–2 hold with hawkish dissents and sticky services inflation — the MPC's reaction function this cycle is genuinely contested among professionals, not just traders.

**N10. Will Google release Gemini 4.0 by 2026-09-30?**
- Type: binary. Resolves: Gemini 4.0 (or clearly-designated successor flagship) publicly accessible — open beta / rolling waitlist counts — per the Polymarket series rules, by 2026-09-30.
- Dates: resolve 2026-09-30. Horizon: **≤3 months**.
- Market: Polymarket `gemini-4pt0-released-by-*` dated series (June-30 rung expired NO; live rungs reprice monthly — capture the Sep-30 rung at cutoff); Manifold `gemini-4-released-in-2026` (83%, already a T5 member — this question is the *dated rung*, not the year).
- Exercises: release-hazard term structure — placing month-by-month mass under a year-probability the desk already tracks; competitive coupling to B18 (GPT-6) makes N10/B18 a correlated pair for T5's band.
- Hard: 83%-by-December is consistent with anywhere from ~25% to ~65% by September — the dated rung is a shipping-cadence judgment the year number doesn't answer.

**N11. What will the Bitcoin price be at 2026-09-30 23:59 UTC?**
- Type: continuous ($). Resolves: CoinGecko BTC-USD spot, 2026-09-30 23:59 UTC. Series: **coingecko `bitcoin`** (wired → specialist SEATS — the plane's first coingecko exercise).
- Dates: resolve 2026-09-30. Horizon: **≤3 months**.
- Market: Kalshi `KXBTCY-27JAN0100` (EOY range board) + `KXBTCMAXY-26DEC31`; Polymarket monthly crypto boards; spot **$64,149** (Jul 10).
- Exercises: first coingecko specialist seat — trend/vol baseline vs LLM regime reasoning in a post-crash year; anchor triangulation across *range boards* rather than a single point market (a harder G8 engagement than a binary price).
- Hard: post-crash regime ($60K February low, choppy recovery, far off the 2025 highs) under macro hike-risk — momentum and mean-reversion baselines point opposite ways and the range boards imply a fat, skewed distribution.

**N12. What will the EUR/USD ECB reference rate be on 2026-09-30?**
- Type: continuous. Resolves: ECB euro reference rate published 2026-09-30 (~16:00 CET). Series: **frankfurter `EUR/USD`** (wired → specialist SEATS — the plane's first frankfurter exercise).
- Dates: resolve 2026-09-30. Horizon: **≤3 months**.
- Market: none liquid named — documented forecaster split instead: spot 1.1438 (Jul 9, near a one-year low) vs Goldman ~1.25 year-end inside a 1.15–1.28 street range.
- Exercises: frankfurter seat + a pure rate-differential question mechanically coupled to N7/N8 — the desk should derive this distribution from its own central-bank grid, and the coupling belongs in a pinned correlation, not independent marginals; no-anchor discipline (G8 dark).
- Hard: both central banks have live hike scenarios pulling the pair opposite ways — the honest distribution is a function of a 2×2 policy grid, not a trend line.

**N13. How many Atlantic named storms will have formed by 2026-09-30?**
- Type: count. Resolves: NHC operational naming, season-to-date through 2026-09-30 23:59 UTC (operational designations as read 2026-10-01). Series: **NHC** — no wired provider → specialist **DECLINES**.
- Dates: resolve 2026-10-01. Horizon: **≤3 months**.
- Market: none direct — Kalshi `KXTROPSTORM-26DEC01` (season total, implied median ~11) is a *related-window* anchor to note and down-weight, not engage.
- Exercises: rung 1 of the N13/N20 ladder — the two rungs plus C5's season total describe one latent formation process, and their implied August/September rates must cohere (a three-question consistency audit); PMF CRPS; decline honesty; T4 member.
- Hard: 1 storm by Jul 10 (Arthur, Jun 17) vs a ~11-by-Sep-30 climatology — El Niño plus record Saharan dust argue for the deepest negative anomaly in years, but a single active August can add 4+ names in three weeks; the ladder punishes anchoring on the dead pace *and* reflexive mean-reversion.

**N14. Which party wins the most votes in Latvia's 2026-10-03 Saeima election?**
- Type: categorical. Resolves: CVK (Central Election Commission) final national vote count, ~2026-10-04.
- Dates: election 2026-10-03, resolve ~2026-10-04. Horizon: **≤3 months**.
- Market: none found 2026-07-10 — polling series instead: PolitPro trend AS (United List) 16.6% vs LPV (Latvia First) 15.0%, while single July polls have them *tied at 9.8%* — the house-effect spread is the story.
- Exercises: no-anchor categorical in a sparse information environment (thin English-language feeds — the B13 triage problem in an electoral setting); G1 tail base rates on a 7-party field; the 5% threshold echoes V4's discontinuity one country over.
- Hard: a 1.6-point trend gap inside enormous house-effect noise, a right-populist front-runner whose turnout is systematically mis-polled across Europe, and no crowd to lean on — pure desk skill.

**N15. What headline YoY CPI will the BLS report for September 2026 (released 2026-10-13)?**
- Type: continuous (%). Resolves: BLS CPI-U NSA 12-month change, September release. Series: **FRED `CPIAUCSL`** (wired → specialist SEATS).
- Dates: resolve 2026-10-13. Horizon: **≤3 months**.
- Market: Kalshi `KXCPIYOY-26SEP` (monthly series; the August rung already trades per T1 — September lists on schedule).
- Exercises: third rung of the CPI chain (C1 June → T1's Aug satellite → N15) — by commit the desk holds two realized prints from its own earlier forecasts, the first same-series lesson-compounding test; T1; **B6 interlock**: an Oct-1 shutdown can delay the release, so the resolution-date risk is itself forecastable.
- Hard: whether C1's energy-base-effect drop extends or stalls against tariff-sticky core — by October this print discriminates the whole T1 regime call, and the specialist has two fresh in-sample points.

### Window B — resolves 2026-10-15 → 2026-12-01 (N16–N25)

**N16. Will Democrats lead the RealClearPolitics generic-congressional-ballot average by ≥5.0 points at close 2026-10-20?** ⚠(snapshot criteria)
- Type: binary. Resolves: the RCP "2026 Generic Congressional Vote" average as displayed 23:59 ET 2026-10-20 (archived capture governs; displayed spread, one decimal).
- Dates: resolve 2026-10-20. Horizon: **≤4 months**.
- Market: none direct — deliberately: Kalshi `KXHOUSEPOPVOTEMARGIN-27NOV03` and T2's PV-margin market price the *November actual*, not this poll-state snapshot.
- Exercises: adversarial resolution wording (which average, which timestamp, pollster-roster drift inside RCP's basket); a fixed-date *information-state* forecast — probability over the polling environment, not the election; T2 leading-indicator member that lets the postmortem decompose poll-state error from poll-to-outcome error on V8/B7–B9.
- Hard: RCP shows D+7.2 today while Economist/YouGov shows D+2 — resolution depends on pollster mix and October news flow, and the base rate for three-month generic-ballot drift is roughly ±3 points.

**N17. Will the FOMC raise the target range at the 2026-10-27/28 meeting?**
- Type: binary. Resolves: Fed implementation note, 2026-10-28 14:00 ET.
- Dates: resolve 2026-10-28. Horizon: **≤4 months**.
- Market: Kalshi `KXFEDDECISION-26OCT` (series verified via the July instance); Polymarket monthly Fed series; CME FedWatch cross-check.
- Exercises: the conditional rung — P(Oct hike) is dominated by what September does (N8), so the belief trajectory must show a regime jump on Sep 16 and the commit should carry pre-registered conditionals (hike-if-Sept-held vs second-hike-if-Sept-hiked) for the Delphi rounds to interrogate; completes the B3/N8/N17/B4 term structure; T1.
- Hard: the unconditional number hides two very different conditionals — desks that don't decompose will end up incoherent against their own N8/B4 commits, and the coherence audit will catch it.

**N18. What advance-estimate annualized real GDP growth will the BEA report for Q3 2026 (released 2026-10-29)?**
- Type: continuous (% SAAR). Resolves: BEA advance estimate, first print. Series: **FRED `A191RL1Q225SBEA`** (wired → specialist SEATS).
- Dates: resolve 2026-10-29. Horizon: **≤4 months**.
- Market: Kalshi `KXGDP-26OCT29` (series verified via the Q2 instance).
- Exercises: C3's rematch with roles revealed — by commit the Q2 print (Jul 30) has resolved the GDPNow-vs-Kalshi wedge, and the desk must decide whether the winner was signal or luck: the first *within-quarter application* of a lesson to the same series; **B6 interlock** (a shutdown delays BEA releases and starves GDPNow of inputs); T1.
- Hard: tariff front-running unwinds and inventory whiplash make Q3 the noisiest print of the year — the desk's own Q2 postmortem is either its edge or its trap.

**N19. Will the Bank of Japan raise its policy rate at the 2026-10-29/30 meeting?**
- Type: binary. Resolves: BoJ Policy Board statement, 2026-10-30 (Outlook Report meeting); any increase from 1.0%.
- Dates: resolve 2026-10-30. Horizon: **≤4 months**.
- Market: Polymarket monthly BoJ series (`bank-of-japan-decision-in-<month>`; June instance verified) — market-implied **>60%** for a hike by October (Bloomberg / Japan Times, Jul 2).
- Exercises: a >60% anchor the blind pool can legitimately fight — the desk owns the reference class (BoJ hikes have historically come slower than markets price); high-velocity yen watched sources; couples to N11/N12 through the global-rates channel.
- Hard: the every-six-months hike cadence says December; the sliding yen and 71%-of-economists survey say October — a clean inside-view-vs-cadence-base-rate fight at a price where being right pays.

**N20. How many Atlantic named storms will have formed by 2026-10-31?**
- Type: count. Resolves: NHC operational naming, season-to-date through 2026-10-31 23:59 UTC (read 2026-11-01). Series: **NHC** — no wired provider → specialist **DECLINES**.
- Dates: resolve 2026-11-01. Horizon: **≤4 months**.
- Market: none direct; Kalshi `KXTROPSTORM-26DEC01` related-window (down-weighted).
- Exercises: rung 2 of the ladder — when N13 resolves Oct 1, G5 should force an N20 re-forecast within days (the cadence machinery's cleanest live test); the increment, not the level, is the forecast; T4; PMF CRPS.
- Hard: October adds ~2 named storms climatologically but ~0–1 in strong El Niño years — desks that update N20 by adding a constant to N13's realization miss the ENSO-conditional increment entirely.

**N21. Who wins the 2026 Georgia governor's race (Bottoms D vs Jackson R)?**
- Type: binary. Resolves: AP/Fox/NBC consensus or certification, 2026-11-03; Georgia's 50%+1 rule means a late-December runoff tail exists.
- Dates: resolve 2026-11-04 (runoff tail ~Dec 29). Horizon: **≤4 months**.
- Market: Polymarket `georgia-governor-winner-2026` (**D 50% / R 48%**); Kalshi `GOVPARTYGA-26`.
- Exercises: the tranche's purest coin flip; joint reasoning with B8 — the same-state Senate market sits at 86.5% D while this sits at 50%, so the market asserts massive ticket-splitting: the desk must either reproduce that conditional structure or register a deviation on one leg (a sharper version of V8's correlation test); T2 member; the runoff rule is a named tail (G1 discipline on a binary).
- Hard: same electorate, same day, two races priced 36 points apart — either one market is wrong or Georgia ticket-splitting is back; both hypotheses are defensible and exactly one scores.

**N22. What will EIA working gas in storage (Lower 48) be for the week ending 2026-10-30 (reported ~2026-11-05)?**
- Type: continuous (Bcf). Resolves: EIA Weekly Natural Gas Storage Report for the injection-season-ending week, released ~2026-11-05. Series: **EIA WNGSR** — no wired provider → specialist **DECLINES**.
- Dates: resolve 2026-11-05. Horizon: **≤4 months**.
- Market: none named — the EIA STEO's own end-of-October forecast (**3,966 Bcf**, 5% above the five-year average) is the published baseline to beat.
- Exercises: decline path on an energy series; an *agency point forecast* as de-facto anchor — the C9 problem without a market: does the desk treat STEO like a crowd or out-argue it; ~16 scheduled weekly reports before resolution make this the densest watched-source cadence in the cohort.
- Hard: current surplus (2,983 Bcf on Jul 3, +6.6% vs 5-yr) vs cooling-demand and LNG-export swings — the terminal level is a sum of 16 weekly increments each with real variance; distribution width is the skill.

**N23. Will the US and China announce a tariff agreement or formal truce extension on or before 2026-11-10?** ⚠(extension vs agreement vs lapse)
- Type: binary. Resolves: official announcement (USTR/White House and MOFCOM-confirmed) of a comprehensive tariff agreement OR a formal extension of the reciprocal-tariff suspension that otherwise expires 2026-11-10; expiry accompanied only by negotiation noise resolves NO.
- Dates: resolve 2026-11-10. Horizon: **≤4 months**.
- Market: Polymarket `us-x-china-tariff-agreement-by-july-31-20260626205549138` (Yes **42.5%**) — the near rung of a dated ladder; later rungs list toward the deadline (capture at cutoff).
- Exercises: criteria-tightness — the May 2026 Trump–Xi Beijing "framework" is exactly the deal-shaped object that must be read against the wording (B11's discipline on a trade file); deadline-hazard shape (mass piles at the buzzer); high-velocity watched feeds; term-structure arbitrage across the rung ladder.
- Hard: the base rate for these truces is extension-at-the-buzzer (2025, twice) — but a framework-without-details plus midterm-season incentives on both sides makes lapse-and-snapback a genuinely live tail.

**N24. What non-GAAP EPS will Nvidia report for Q3 FY2027 (report ~2026-11-18)?**
- Type: continuous ($). Resolves: NVDA Q3 FY2027 earnings release (8-K / press release), non-GAAP diluted EPS. Series: **company IR** — no wired provider → specialist **DECLINES**.
- Dates: resolve ~2026-11-18. Horizon: **≤4.5 months**.
- Market: Polymarket per-quarter series `nvda-quarterly-earnings-nongaap-eps-<date>-<consensus>` (May instance verified; its beat-consensus binary priced ~100% — which is exactly why this question asks for the *level*, not the beat).
- Exercises: the AI-infra scarcity thesis (T5/B19) cashed into one auditable number; CRPS against a consensus that itself drifts (the anchor moves — snapshot discipline); B19 interlock — this print is B19's named single-earnings flip hazard.
- Hard: "will they beat" is a 95% gimme; *by how much* — against supply-constrained guidance, hyperscaler capex revisions, and China licensing noise — is a wide distribution the beat-rate base rate says nothing about.

**N25. Will the COP31 cover decision include an explicit fossil-fuel transition commitment?** ⚠(which text counts)
- Type: binary. Resolves: the COP31/CMA cover decision(s) formally adopted at Antalya (2026-11-09–20) contain an explicit reference to "transitioning away from fossil fuels" or stronger phase-down/phase-out language; UNFCCC-published decision text governs — side declarations and presidency statements don't count.
- Dates: conference 2026-11-09–20 (leaders' summit Nov 11–12), resolve ~2026-11-21. Horizon: **≤4.5 months**.
- Market: none found 2026-07-10 — negotiation-text watched sources and expert commentary carry it.
- Exercises: adversarial criteria at treaty-text granularity — which document is "the cover decision" when a COP splits its texts (the B12 problem in multilateral form); a hard-deadline evidence crescendo in week 2; T4-adjacent (climate politics decoupled from climate physics).
- Hard: COP28 set the phrase precedent, the Belém round conspicuously dropped it, and the Türkiye-host / Australia-president split presidency makes the final text a bargaining artifact — the base rate on final-week COP language is near-uninformative.

---

## 3. Observation plan — what to measure while the engine runs

### 3.1 Per-question instrumentation

| Signal | Where it is recorded | What it discriminates |
|---|---|---|
| Belief-trajectory depth: steps per panelist run, |Δp| per step, which step moved the number most | panel metadata (BLF A1 trajectory `(t, p_t, what_moved_it)`) | Whether the panelists actually update on evidence vs reason-once; feeds desk notes + postmortems |
| Panel disagreement index + shrinkage α | quorum result (`disagreement`, variance-adaptive α, A3) | Contested vs calm questions; whether α correctly leans on the anchor when trials are noisy |
| K-trial spread (high-impact) | per-seat trial logits | Inter-trial σ per model (BLF found σ≈0.20); lone-skeptic detection rate |
| Delphi round movement | `delphi_rounds` + `delphi_audit` | Whether revision rounds converge or herd |
| Blind-pool vs reconciled-pool vs market | panel run annotations (`blind_pool`, `reconciled_pool`, `market_anchor`) | Orthogonality r of the blind pool (Live-Edge baseline: r 0.92→0.765); anchor-pull magnitude |
| Deviation bets: count, direction, pre-registered edge, resolution outcome | `ledger/deviation_bets.py` (currently **0 rows ever** — the gauntlet must change this) | Whether >10pp disagreements are skill or noise; feeds the G8 promotion precondition (first scored cohort ≥10) |
| Gate fires: per-rule fire + remediation counts, time-to-remediate | `metadata['saturation']` verdicts, `forecast lint --by-rule`, doctor scorecard | Which gates bind under load; G1 fires on every share board's first commit are *expected and intended* |
| Specialist seats: seated/declined per question, decline reason | quorum seat records (`SpecialistDeclined` labeled) | Data-plane coverage honesty; the NOAA/USGS questions MUST show declines |
| Specialist-vs-LLM CRPS delta | resolution scoring per panelist id (`model:climatology_knn`, `model:seasonal_naive`) vs LLM seats | The BLF A5 thesis: does the KNN earn pool share on seasonal series; does the LLM beat it on regime breaks |
| Per-candidate interval coverage (share boards) | G2 P2 resolution scoring (`[p05,p95]` hit rate, target ~90%) | Interval calibration on the vote-share arm |
| Triage volume + label distribution + contested-routing rate | `label_scoring.py` ledger (relevant/irrelevant/contested; operator hand-label queue) | Whether the 80% trust gate holds at 50-question news volume |
| Update cadence adherence | G5 verdicts, review-queue reasons, `stale_evidence_reason` usage | Set-and-forget detection on the long-horizon arm |
| Thesis band honesty | thesis aggregate `p_ci90`/`p_sd` vs member correlation matrix (`set_thesis_correlation`) | Whether pinned ρ widens bands vs the naive independent product |

### 3.2 Aggregate readouts

- **Difficulty-adjusted Brier vs the crowd** — the ABI-style cohort recentring
  (`ledger/scoring.py`): raw Brier is composition-confounded; the gauntlet is
  deliberately hard, so only the difficulty-adjusted column is meaningful. Paired,
  per-question edge vs the frozen market baseline (benchmarking memo §9), clustered CI.
- **Blind-pool orthogonality r** vs market across the ≥25 anchored questions —
  the Live-Edge replication at 3–4× the n.
- **Calibration curve by domain** (geopolitics / elections / macro / AI / climate /
  finance / health) and by horizon rung — expect domain-heterogeneous miscalibration;
  that heterogeneity is what the hierarchical per-source Platt (BLF A4) will need.
- **CRPS ladder on the continuous arm**: LLM pool vs climatology KNN vs seasonal-naive
  per question, plus the pooled quorum — the specialists must win somewhere (CPI
  climatology in a stable regime) and lose somewhere (regime-break prints) or the
  track-record weighting has nothing to learn from.
- **VOI ranking quality**: rank-correlation between the VOI queue's ordering and
  realized |Δp| over the following week — did the queue actually point at the questions
  whose beliefs were about to move?
- **Lesson loop throughput**: resolutions → auto-postmortems → synthesized lessons →
  compiled `lesson:*` rules that fire on later gauntlet commits (the ≤1-month rung
  exists to feed this within the observation window).
- **Deviation-bet P&L** (paper): pre-registered edges scored at resolution — the
  Track-D readout, reported separately from the headline (it is a conditional stratum,
  not an unbiased skill estimate).

### 3.3 The load dimension — what 50 concurrent live questions stress

50 live-origin questions with watched sources, weekly-or-tighter cadences, quorum jobs,
and market snapshots is roughly a 3–4× step over the current live book (175 live-origin
currents). Specific pressure points, with the dashboards to watch:

| Pressure point | Mechanism under load | Watch |
|---|---|---|
| Cron sweep saturation | 10-min gateway due-sweeps (`cron_runner.resolve_review_sweep_interval_minutes`) + nightly deterministic sweep now iterate 50 more active questions; the deadline-aware cadence clamp tightens as short-fuse questions approach close | sweep duration trend; `run_due_scheduled_reviews` backlog |
| Alert governance | saturation/cadence/watch alerts are deduped and drained at the free-tier cap (default 500/sweep, `resolve_free_tier_sweep_cap`); 50 questions × G3/G5/G7 WARN debt can spike the drain queue | warnings drain depth; `forecast lint --by-rule` failed_warn trend (it must fall, not plateau) |
| Refresh volume | evidence refresh + watched-source polls scale with feeds, not questions — the fast-mover arm (≥10 questions × 2–4 feeds) dominates; triage inference cost rides on top | refresh job durations; triage queue depth; contested-routing (hand-label) rate — if it climbs past the operator's capacity the 80% trust gate is being outrun |
| LLM spend | quorum K=3 on high-impact × Delphi rounds × 5+ seats; the jobs policy matrix per-job caps + `budget.py` box-level ceilings (default **unlimited** — set them BEFORE the gauntlet) | `{home}/spend/` meter; `forecast config doctor` budget panel |
| Market snapshot cadence | ≥25 anchored questions need time-matched market snapshots at every scored checkpoint (benchmarking memo §7) — nightly at minimum, tighter near close | snapshot gap report; any scored update without a matched market snapshot is relabeled "vs initial baseline" |
| Resolution + postmortem burst | the ≤1-month rung lands ~10 resolutions in weeks 1–5, each triggering scoring + postmortem + lesson synthesis | resolution detector lag; postmortem completion rate |
| Gate-fire burst at onboarding | 10 share boards hit G1/G2 on first commit by design; expect a visible SaturationBlocked burst in week 1 with agent-side remediation | doctor scorecard failed_block column (must go to zero within one cadence cycle) |

**Pre-flight checklist:** set `budget.py` ceilings; confirm FRED/BLS API keys
(`marketdata/keys.py`) so specialists seat; attach `metadata['series']` hints at
creation; register watched sources per question; commit everything live-origin; freeze
market baselines at cutoff with raw payload + hash (benchmarking memo §16 items 1–10).

**What the fast tranche (§2b) uniquely enables.** Tranche 2 turns the lesson loop from
a promise into a measured, multi-turn process inside one quarter: the July resolutions
(N1–N3) produce the cohort's first scored postmortems within days of onboarding; the
lessons they synthesize compile into `lesson:*` hooks that must demonstrably bite on the
September commits (N5–N9); those resolve and postmortem in time to re-forecast the
late-October/November cluster (N16–N25) — **two full score→postmortem→lesson→apply turns
before December**, where the core 50 alone would not complete one until 2027. It also
stresses the cadence machinery in its tight regime rather than its weekly default: ~20
dated catalysts (prints, meetings, matches, deadlines) inside twelve weeks push the G5
deadline clamp toward daily-to-48-hour reviews, demand time-matched market snapshots
near close on a dozen anchored questions at once, and concentrate refresh/triage bursts
around release timestamps — if update cadence, VOI ordering (the §3.2 rank-correlation
readout becomes measurable in weeks, not months), or the postmortem pipeline saturates
under high-frequency updating, this tranche is where it shows first. Finally, its ~25
resolutions by 2026-12-01 fill the G8 deviation-bet promotion precondition (first scored
cohort ≥10) entirely within the observation quarter.

---

## 4. Relation to the benchmark program

This gauntlet is the **Track C/E hybrid cohort** the benchmarking-strategy memo calls
for: Tier-A admission (external resolvers, liquid anchors, evidence-rich), pre-registered
before outcomes, artifact-complete (rationales, evidence records, run records — the
gaps the 292-question pilot had). It is *not* the powered Track-B confirmatory market-edge
cohort (n=50 is under-powered for a small Brier edge); its claims are: the machinery held
under load, every subsystem produced its intended artifacts, and the case audits are
inspectable end-to-end. Report it that way.
