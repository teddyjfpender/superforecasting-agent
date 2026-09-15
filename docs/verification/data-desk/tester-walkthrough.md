# Try the global data desk

Use a fresh profile with the normal supported installation. Setup offers **Global
starter set** or **Start empty**. The starter adds data collections, not forecasts,
resolutions or calibration lessons. Source access can vary by region and quota.

## Start populated

Choose the global starter during setup. Optionally select a home region and weather
locations, review the proposed rows, and apply. The default contains 163 entries,
including official economics, market prices and environmental feeds. Data arrives
progressively; an unavailable provider should not blank the other rows.

Weather model forecasts, air-quality forecasts and historical reanalysis are
labeled separately. NWS severe-weather feeds show events rather than prices.
Monthly and annual values retain their observation periods; a recently retrieved
value is not necessarily a recently measured value.

## Start empty, then adopt defaults

Choose **Start empty**, close the application, and reopen it. The desk should
remain empty. Choose **Load global starter set**, or open **Add data → Starter
sets**. Review the additions and apply. Repeating this operation adds only missing
series and preserves saved prediction markets, watchlists and custom symbols.

## Browse and connect sources

**Browse data** supports text search plus topic, region, country and data-kind
filters. Inspect a row's geography, unit, source, revision policy and latest data.
Type directly to search; Left/Right selects a topic and Tab changes views.
Ctrl+R, Ctrl+G and Ctrl+K change region, country and kind. Ctrl+L loads the
latest observation. Page Up/Down scrolls source details on smaller terminals.
Enter toggles an indicator, then Ctrl+S reviews your changes before applying. Changes require explicit preview and apply. Escape
abandons the uncommitted selection.

**Sources** describes coverage and access requirements. Optional provider keys use
a masked prompt and are stored by the connected backend. A saved key indicates
configuration, not successful provider verification. On a VPS connection, the
VPS owns the selection and credentials.

## Navigate the desk

Left/Right or Tab changes topics, including while viewing prediction markets.
Shift+Tab moves backward. Space expands or collapses prediction-market outcomes;
Enter opens the selected market. Topic labels use available terminal width.

Quote tables give spare width to names, omit VOL when every visible value is
missing, and show a compact TREND. A trend is the latest observations, not
necessarily one month. Source errors appear in the selected row details.

## CLI equivalents

```sh
superforecasting-agent data catalog --region europe
superforecasting-agent data selection
superforecasting-agent data preset global
superforecasting-agent data preset global --apply
```

The command without `--apply` previews changes. To inspect the intentionally empty
operation and other options, use `superforecasting-agent data --help`.

## Report unexpected behavior

Include the installed version, provider and catalog series ID, visible status,
expected behavior, and whether the backend was local or remote. Never include API
keys or a raw `.env` file. The [qualification report](qualification.md) documents
conditional providers and known history/release-metadata limitations.
