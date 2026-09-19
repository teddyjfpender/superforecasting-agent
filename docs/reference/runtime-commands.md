# Runtime command inventory

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: superforecasting_agent/runtime/main.py (build_runtime_parser) -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `superforecasting_agent/runtime/main.py (build_runtime_parser)`

Built-in command paths, parser aliases and bound dispatch callbacks, derived from the same parser used at runtime.

Plugin commands are intentionally excluded from this built-in inventory: they depend on installed plugins and the active profile. The CLI opts into discovery for possible plugin invocations; metadata inspection does not execute plugin registration hooks.

The output column records parser flags only. It does not establish a machine-output schema, noninteractive completion, or parity with messaging/TUI. A parent callback is inherited where a subcommand does not bind a separate handler. See [slash-command surfaces](command-surfaces.md) for the separate interactive registry.

## Entrypoint routing

This is the runtime parser inventory, not an exhaustive public routing table. `superforecasting_agent/cli.py::main` handles version flags, `tui`, environment-enabled desk startup, profile import and `snapshot` before runtime parsing. It also routes forecast shorthand (including overlapping names such as `status`) to the forecast parser; runtime `config` remains separate from forecast `config doctor`. See the [forecast reference](cli-reference.md). The callbacks below describe runtime-parser bindings, not proof that every same-named public invocation reaches them.

## Runtime parser bindings

| Command | Parser aliases | Dispatch callback | Output flag |
| --- | --- | --- | --- |
| `superforecasting-agent chat` | `desk` | `superforecasting_agent.runtime.main.cmd_chat` | not declared here |
| `superforecasting-agent forecast` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast about` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast status` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast bench` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast lifecycle` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast doctor` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast backup` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast backup run` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast backup list` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast lint` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast hooks` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks list` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast hooks profiles` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks promotions` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast hooks explain` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks lint` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks methods` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks preview` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast hooks set-severity` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks set-profile` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks enable` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks disable` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks edit` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast hooks remove` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast sources` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast new` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast onboard` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast next` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast search` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast show` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast set-decision` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast update` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast refresh` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast freshen` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast ingest` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import packet` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast import metaculus` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import market` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import manifold` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import polymarket` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import kalshi` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import benchmark` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import tournament` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import news` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import data` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import gdelt` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import fivethirtyeight` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import github` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import githubrepo` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import githubissues` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import githubcommits` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import githubactions` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import pypi` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import npm` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import hackernews` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import reddit` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import bluesky` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import mastodon` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import reliefweb` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import federalregister` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import courtlistener` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import nvd` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import cisakev` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import openmeteo` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import airquality` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import weatherhistory` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import usgs` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import eonet` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import nws` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import clinicaltrials` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import openfda` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import pubmed` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import owid` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import whogho` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import fema` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import fred` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import eia` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import treasury` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import bls` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import worldbank` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import imf` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import census` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import socrata` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import ckan` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import stooq` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import yahoo` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import coingecko` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import sec` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import secfacts` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import arxiv` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import openalex` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import crossref` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import wikipedia` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast import wikipediapageviews` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast tournament` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast plugins` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast research` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast base-rate` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast model` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast bayes` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast panel` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast panel perspectives` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast panel aggregate` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast panel record` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast panel show` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast panel list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast quorum` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast rerun` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast api-key` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast api-key list` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast api-key show` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast api-key set` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast api-key unset` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast config` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast config doctor` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast protocol` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast pipeline` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast agent` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast assumption` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast assumption add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast assumption list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast assumption status` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast reference-class` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast reference-class list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast reference-class status` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast reference-class relink` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast crux` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast crux add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast crux list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast crux status` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast crux backfill` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast intervals` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast intervals backfill` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast evidence-map` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast evidence` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast evidence add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast evidence list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast resolve` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast score` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast scores` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast postmortem` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast censoring-policy` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast domain` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial create` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial run` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial report` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial recover` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial export` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial candidates` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast trial preflight` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast facts` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast facts show` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast facts verify-import` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast facts bind` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast facts bind-settlement` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast facts bind-source` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lesson` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lesson create` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lesson list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lesson status` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lesson synthesize` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lessons` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lessons audit` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast lessons effectiveness` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast lessons explain` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast lessons apply` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast correction` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast correction add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast correction apply` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast correction list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast resolver` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast resolver trust` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast resolver list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast resolver rule` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast resolver propose` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast resolver propose-due` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast calibration` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast scoreboard` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast scoreboard board` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast scoreboard audit` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast scoreboard quarantine` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast scoreboard backfill-crps` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast scoreboard postmortem-misses` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast practice` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast drill` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast complementarity` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast ablation` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast market-nightly` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast market-nightly sample` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast market-nightly run` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast market-nightly score` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast market-nightly report` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast edge` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast tail-audit` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast market-quality` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast track-record` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast errors` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast review` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule dedupe` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast schedule run` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule history` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast schedule install-cron` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule automode-cron` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule automode-cron start` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule automode-cron stop` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast schedule automode-cron status` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast cycle` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast cycle run` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast warnings` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast warnings list` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast warnings resolve` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast warnings automode` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast watch` | `source` | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast watch add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast watch list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast watch check` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage label` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage contested` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage relabel` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage trust` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage set-rubric` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triage list-rubrics` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast link` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast link add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast link list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast link remove` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast links` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast unlink` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis create` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis tag` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis untag` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis members` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast thesis aggregate` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis set-correlation` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis set-event` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis member-intervals` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast thesis show` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis dashboard` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast thesis entity` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis entity add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis entity weight` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis entity remove` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast thesis entity list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor create` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor add` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor remove` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor list` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor aggregate` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast factor show` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast curate` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast run-all` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot enable` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot disable` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot status` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot run` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot history` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot proposals` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot approve` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast autopilot reject` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast alerts` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast self-check` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast triggers` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast backtest` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast performance` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast readiness` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast pilot-report` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast pilot-cohort` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast pilot-aggregate` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast pilot-bundle` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast export` | — | `forecasting.cli.core.cmd_forecast` | `--format` |
| `superforecasting-agent forecast jobs` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast jobs status` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast jobs active` | `list` | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast jobs cancel` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast jobs approve` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast slack` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast slack provision` | — | `forecasting.cli.core.cmd_forecast` | `--format` |
| `superforecasting-agent forecast slack whoami` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast slack share` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast connect` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast connect telegram` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast connect slack` | — | `forecasting.cli.core.cmd_forecast` | `--format`, `--json` |
| `superforecasting-agent forecast connect signal` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast connect whatsapp` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast notify` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent forecast notify list` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast notify test` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast notify add` | — | `forecasting.cli.core.cmd_forecast` | `--json` |
| `superforecasting-agent forecast notify remove` | — | `forecasting.cli.core.cmd_forecast` | not declared here |
| `superforecasting-agent workspace` | — | `parent dispatch / help` | not declared here |
| `superforecasting-agent workspace init` | — | `forecasting.cli.collaboration_admin._cmd_init` | `--json` |
| `superforecasting-agent workspace clone` | — | `forecasting.cli.collaboration_admin._cmd_clone` | `--json` |
| `superforecasting-agent workspace link` | — | `forecasting.cli.collaboration_admin._cmd_link` | `--json` |
| `superforecasting-agent workspace status` | — | `forecasting.cli.collaboration_admin._cmd_status` | `--json` |
| `superforecasting-agent workspace pull` | — | `forecasting.cli.collaboration_admin._cmd_pull` | `--json` |
| `superforecasting-agent workspace export` | — | `forecasting.cli.collaboration_admin._cmd_export` | `--json` |
| `superforecasting-agent workspace reconcile` | — | `forecasting.cli.collaboration_admin._cmd_reconcile` | `--json` |
| `superforecasting-agent github` | — | `parent dispatch / help` | not declared here |
| `superforecasting-agent github auth` | — | `forecasting.cli.collaboration_admin._cmd_github_auth` | `--json` |
| `superforecasting-agent github install` | — | `forecasting.cli.collaboration_admin._cmd_github_install` | `--json` |
| `superforecasting-agent github status` | — | `forecasting.cli.collaboration_admin._cmd_github_status` | `--json` |
| `superforecasting-agent github revoke` | — | `forecasting.cli.collaboration_admin._cmd_github_revoke` | `--json` |
| `superforecasting-agent changeset` | — | `parent dispatch / help` | not declared here |
| `superforecasting-agent changeset list` | — | `forecasting.cli.collaboration_admin._cmd_changeset_list` | `--json` |
| `superforecasting-agent changeset show` | — | `forecasting.cli.collaboration_admin._cmd_changeset_show` | `--json` |
| `superforecasting-agent changeset preview` | — | `forecasting.cli.collaboration_admin._cmd_changeset_preview` | `--json` |
| `superforecasting-agent changeset review-policy` | — | `forecasting.cli.collaboration_admin._cmd_review_policy` | `--json` |
| `superforecasting-agent changeset review-status` | — | `forecasting.cli.collaboration_admin._cmd_review_status` | `--json` |
| `superforecasting-agent changeset transcript-retention` | — | `forecasting.cli.collaboration_admin._cmd_transcript_retention` | `--json` |
| `superforecasting-agent changeset transcript-access-audit` | — | `forecasting.cli.collaboration_admin._cmd_transcript_access_audit` | `--json` |
| `superforecasting-agent changeset apply` | — | `forecasting.cli.collaboration_admin._cmd_changeset_apply` | `--json` |
| `superforecasting-agent changeset retry` | — | `forecasting.cli.collaboration_admin._cmd_changeset_retry` | `--json` |
| `superforecasting-agent changeset abandon` | — | `forecasting.cli.collaboration_admin._cmd_changeset_abandon` | `--json` |
| `superforecasting-agent data` | — | `superforecasting_agent.runtime.data_desk.run` | not declared here |
| `superforecasting-agent data catalog` | — | `superforecasting_agent.runtime.data_desk.run` | not declared here |
| `superforecasting-agent data selection` | — | `superforecasting_agent.runtime.data_desk.run` | not declared here |
| `superforecasting-agent data preset` | — | `superforecasting_agent.runtime.data_desk.run` | not declared here |
| `superforecasting-agent data empty` | — | `superforecasting_agent.runtime.data_desk.run` | not declared here |
| `superforecasting-agent data select` | — | `superforecasting_agent.runtime.data_desk.run` | not declared here |
| `superforecasting-agent model` | — | `superforecasting_agent.runtime.main.cmd_model` | not declared here |
| `superforecasting-agent fallback` | — | `superforecasting_agent.runtime.fallback_cmd.cmd_fallback` | not declared here |
| `superforecasting-agent fallback list` | `ls` | `superforecasting_agent.runtime.fallback_cmd.cmd_fallback` | not declared here |
| `superforecasting-agent fallback add` | — | `superforecasting_agent.runtime.fallback_cmd.cmd_fallback` | not declared here |
| `superforecasting-agent fallback remove` | `rm` | `superforecasting_agent.runtime.fallback_cmd.cmd_fallback` | not declared here |
| `superforecasting-agent fallback clear` | — | `superforecasting_agent.runtime.fallback_cmd.cmd_fallback` | not declared here |
| `superforecasting-agent gateway` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway run` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway start` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway stop` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway restart` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway status` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway install` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway uninstall` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway list` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway setup` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent gateway migrate-legacy` | — | `superforecasting_agent.runtime.main.cmd_gateway` | not declared here |
| `superforecasting-agent proxy` | — | `superforecasting_agent.runtime.main.cmd_proxy` | not declared here |
| `superforecasting-agent proxy start` | — | `superforecasting_agent.runtime.main.cmd_proxy` | not declared here |
| `superforecasting-agent proxy status` | — | `superforecasting_agent.runtime.main.cmd_proxy` | not declared here |
| `superforecasting-agent proxy providers` | — | `superforecasting_agent.runtime.main.cmd_proxy` | not declared here |
| `superforecasting-agent lsp` | — | `agent.lsp.cli.run_lsp_command` | not declared here |
| `superforecasting-agent lsp status` | — | `agent.lsp.cli.run_lsp_command` | `--json` |
| `superforecasting-agent lsp list` | — | `agent.lsp.cli.run_lsp_command` | not declared here |
| `superforecasting-agent lsp install` | — | `agent.lsp.cli.run_lsp_command` | not declared here |
| `superforecasting-agent lsp install-all` | — | `agent.lsp.cli.run_lsp_command` | not declared here |
| `superforecasting-agent lsp restart` | — | `agent.lsp.cli.run_lsp_command` | not declared here |
| `superforecasting-agent lsp which` | — | `agent.lsp.cli.run_lsp_command` | not declared here |
| `superforecasting-agent setup` | — | `superforecasting_agent.runtime.main.cmd_setup` | not declared here |
| `superforecasting-agent postinstall` | — | `superforecasting_agent.runtime.main.cmd_postinstall` | not declared here |
| `superforecasting-agent whatsapp` | — | `superforecasting_agent.runtime.main.cmd_whatsapp` | not declared here |
| `superforecasting-agent slack` | — | `superforecasting_agent.runtime.main.cmd_slack` | not declared here |
| `superforecasting-agent slack manifest` | — | `superforecasting_agent.runtime.main.cmd_slack` | not declared here |
| `superforecasting-agent send` | — | `superforecasting_agent.runtime.send_cmd.cmd_send` | `--json` |
| `superforecasting-agent login` | — | `superforecasting_agent.runtime.main.cmd_login` | not declared here |
| `superforecasting-agent logout` | — | `superforecasting_agent.runtime.main.cmd_logout` | not declared here |
| `superforecasting-agent auth` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent auth add` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent auth list` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent auth remove` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent auth reset` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent auth status` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent auth logout` | — | `superforecasting_agent.runtime.main.cmd_auth` | not declared here |
| `superforecasting-agent status` | — | `superforecasting_agent.runtime.main.cmd_status` | not declared here |
| `superforecasting-agent cron` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron list` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron create` | `add` | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron edit` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron pause` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron resume` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron run` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron remove` | `rm`, `delete` | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron status` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent cron tick` | — | `superforecasting_agent.runtime.main.cmd_cron` | not declared here |
| `superforecasting-agent webhook` | — | `superforecasting_agent.runtime.main.cmd_webhook` | not declared here |
| `superforecasting-agent webhook subscribe` | `add` | `superforecasting_agent.runtime.main.cmd_webhook` | not declared here |
| `superforecasting-agent webhook list` | `ls` | `superforecasting_agent.runtime.main.cmd_webhook` | not declared here |
| `superforecasting-agent webhook remove` | `rm` | `superforecasting_agent.runtime.main.cmd_webhook` | not declared here |
| `superforecasting-agent webhook test` | — | `superforecasting_agent.runtime.main.cmd_webhook` | not declared here |
| `superforecasting-agent kanban` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban init` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards list` | `ls` | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban boards create` | `new` | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards rm` | `remove`, `delete` | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards switch` | `use` | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards show` | `current` | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards rename` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban boards set-default-workdir` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban create` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban swarm` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban list` | `ls` | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban show` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban assign` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban reclaim` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban reassign` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban diagnostics` | `diag` | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban link` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban unlink` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban claim` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban comment` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban complete` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban edit` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban block` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban schedule` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban unblock` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban archive` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban tail` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban dispatch` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban daemon` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban watch` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban stats` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban notify-subscribe` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban notify-list` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban notify-unsubscribe` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban log` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban runs` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban heartbeat` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban assignees` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban context` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent kanban specify` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban decompose` | — | `superforecasting_agent.runtime.main.cmd_kanban` | `--json` |
| `superforecasting-agent kanban gc` | — | `superforecasting_agent.runtime.main.cmd_kanban` | not declared here |
| `superforecasting-agent hooks` | — | `superforecasting_agent.runtime.main.cmd_hooks` | not declared here |
| `superforecasting-agent hooks list` | `ls` | `superforecasting_agent.runtime.main.cmd_hooks` | not declared here |
| `superforecasting-agent hooks test` | — | `superforecasting_agent.runtime.main.cmd_hooks` | not declared here |
| `superforecasting-agent hooks revoke` | `remove`, `rm` | `superforecasting_agent.runtime.main.cmd_hooks` | not declared here |
| `superforecasting-agent hooks doctor` | — | `superforecasting_agent.runtime.main.cmd_hooks` | not declared here |
| `superforecasting-agent doctor` | — | `superforecasting_agent.runtime.main.cmd_doctor` | not declared here |
| `superforecasting-agent security` | — | `superforecasting_agent.runtime.main.cmd_security` | not declared here |
| `superforecasting-agent security audit` | — | `superforecasting_agent.runtime.main.cmd_security` | `--json` |
| `superforecasting-agent dump` | — | `superforecasting_agent.runtime.main.cmd_dump` | not declared here |
| `superforecasting-agent debug` | — | `superforecasting_agent.runtime.main.cmd_debug` | not declared here |
| `superforecasting-agent debug share` | — | `superforecasting_agent.runtime.main.cmd_debug` | not declared here |
| `superforecasting-agent debug delete` | — | `superforecasting_agent.runtime.main.cmd_debug` | not declared here |
| `superforecasting-agent backup` | — | `superforecasting_agent.runtime.main.cmd_backup` | not declared here |
| `superforecasting-agent checkpoints` | — | `superforecasting_agent.runtime.checkpoints.cmd_status` | not declared here |
| `superforecasting-agent checkpoints status` | — | `superforecasting_agent.runtime.checkpoints.cmd_status` | not declared here |
| `superforecasting-agent checkpoints list` | — | `superforecasting_agent.runtime.checkpoints.cmd_list` | not declared here |
| `superforecasting-agent checkpoints prune` | — | `superforecasting_agent.runtime.checkpoints.cmd_prune` | not declared here |
| `superforecasting-agent checkpoints clear` | — | `superforecasting_agent.runtime.checkpoints.cmd_clear` | not declared here |
| `superforecasting-agent checkpoints clear-legacy` | — | `superforecasting_agent.runtime.checkpoints.cmd_clear_legacy` | not declared here |
| `superforecasting-agent import` | — | `superforecasting_agent.runtime.main.cmd_import` | not declared here |
| `superforecasting-agent config` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config show` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config edit` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config set` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config path` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config env-path` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config check` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent config migrate` | — | `superforecasting_agent.runtime.main.cmd_config` | not declared here |
| `superforecasting-agent pairing` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_pairing` | not declared here |
| `superforecasting-agent pairing list` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_pairing` | not declared here |
| `superforecasting-agent pairing approve` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_pairing` | not declared here |
| `superforecasting-agent pairing revoke` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_pairing` | not declared here |
| `superforecasting-agent pairing clear-pending` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_pairing` | not declared here |
| `superforecasting-agent skills` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills browse` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills search` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills install` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills inspect` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills list` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills check` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills update` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills audit` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills uninstall` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills reset` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills publish` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills snapshot` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills snapshot export` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills snapshot import` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills tap` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills tap list` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills tap add` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills tap remove` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent skills config` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_skills` | not declared here |
| `superforecasting-agent bundles` | — | `superforecasting_agent.runtime.bundles.bundles_command` | not declared here |
| `superforecasting-agent bundles list` | — | `superforecasting_agent.runtime.bundles.bundles_command` | not declared here |
| `superforecasting-agent bundles show` | — | `superforecasting_agent.runtime.bundles.bundles_command` | not declared here |
| `superforecasting-agent bundles create` | — | `superforecasting_agent.runtime.bundles.bundles_command` | not declared here |
| `superforecasting-agent bundles delete` | — | `superforecasting_agent.runtime.bundles.bundles_command` | not declared here |
| `superforecasting-agent bundles reload` | — | `superforecasting_agent.runtime.bundles.bundles_command` | not declared here |
| `superforecasting-agent plugins` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent plugins install` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent plugins update` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent plugins remove` | `rm`, `uninstall` | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent plugins list` | `ls` | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent plugins enable` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent plugins disable` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_plugins` | not declared here |
| `superforecasting-agent curator` | — | `superforecasting_agent.runtime.curator.register_cli.<locals>.<lambda>` | not declared here |
| `superforecasting-agent curator status` | — | `superforecasting_agent.runtime.curator._cmd_status` | not declared here |
| `superforecasting-agent curator run` | — | `superforecasting_agent.runtime.curator._cmd_run` | not declared here |
| `superforecasting-agent curator pause` | — | `superforecasting_agent.runtime.curator._cmd_pause` | not declared here |
| `superforecasting-agent curator resume` | — | `superforecasting_agent.runtime.curator._cmd_resume` | not declared here |
| `superforecasting-agent curator pin` | — | `superforecasting_agent.runtime.curator._cmd_pin` | not declared here |
| `superforecasting-agent curator unpin` | — | `superforecasting_agent.runtime.curator._cmd_unpin` | not declared here |
| `superforecasting-agent curator restore` | — | `superforecasting_agent.runtime.curator._cmd_restore` | not declared here |
| `superforecasting-agent curator list-archived` | — | `superforecasting_agent.runtime.curator._cmd_list_archived` | not declared here |
| `superforecasting-agent curator archive` | — | `superforecasting_agent.runtime.curator._cmd_archive` | not declared here |
| `superforecasting-agent curator prune` | — | `superforecasting_agent.runtime.curator._cmd_prune` | not declared here |
| `superforecasting-agent curator backup` | — | `superforecasting_agent.runtime.curator._cmd_backup` | not declared here |
| `superforecasting-agent curator rollback` | — | `superforecasting_agent.runtime.curator._cmd_rollback` | not declared here |
| `superforecasting-agent memory` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_memory` | not declared here |
| `superforecasting-agent memory setup` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_memory` | not declared here |
| `superforecasting-agent memory status` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_memory` | not declared here |
| `superforecasting-agent memory off` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_memory` | not declared here |
| `superforecasting-agent memory reset` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_memory` | not declared here |
| `superforecasting-agent tools` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_tools` | not declared here |
| `superforecasting-agent tools list` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_tools` | not declared here |
| `superforecasting-agent tools disable` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_tools` | not declared here |
| `superforecasting-agent tools enable` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_tools` | not declared here |
| `superforecasting-agent computer-use` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_computer_use` | not declared here |
| `superforecasting-agent computer-use install` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_computer_use` | not declared here |
| `superforecasting-agent computer-use status` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_computer_use` | not declared here |
| `superforecasting-agent mcp` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp serve` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp add` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp remove` | `rm` | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp list` | `ls` | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp test` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp configure` | `config` | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent mcp login` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_mcp` | not declared here |
| `superforecasting-agent sessions` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions list` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions export` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions delete` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions prune` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions stats` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions rename` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent sessions browse` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_sessions` | not declared here |
| `superforecasting-agent insights` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_insights` | not declared here |
| `superforecasting-agent claw` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_claw` | not declared here |
| `superforecasting-agent claw migrate` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_claw` | not declared here |
| `superforecasting-agent claw cleanup` | `clean` | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_claw` | not declared here |
| `superforecasting-agent version` | — | `superforecasting_agent.runtime.main.cmd_version` | not declared here |
| `superforecasting-agent update` | — | `superforecasting_agent.runtime.main.cmd_update` | not declared here |
| `superforecasting-agent uninstall` | — | `superforecasting_agent.runtime.main.cmd_uninstall` | not declared here |
| `superforecasting-agent acp` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.cmd_acp` | not declared here |
| `superforecasting-agent profile` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile list` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile use` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile create` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile delete` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile describe` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile show` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile alias` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile rename` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile export` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile import` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile install` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile update` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent profile info` | — | `superforecasting_agent.runtime.main.cmd_profile` | not declared here |
| `superforecasting-agent completion` | — | `superforecasting_agent.runtime.main.build_runtime_parser.<locals>.<lambda>` | not declared here |
| `superforecasting-agent dashboard` | — | `superforecasting_agent.runtime.main.cmd_dashboard` | not declared here |
| `superforecasting-agent logs` | — | `superforecasting_agent.runtime.main.cmd_logs` | not declared here |
