# Data-desk source qualification

The initial delivery contains 219 catalog entries and a 163-entry global preset.
Admission here means usable display data, not permission to settle a forecast.
The preset contains 159 numerical series and four NWS event feeds. CoinGecko's
five spot rows do not provide dated history through the current adapter.

## Coverage and evidence

| Family | Scope | Evidence and limits |
| --- | --- | --- |
| World Bank | 50 country indicators | All 50 returned values in the follow-up receipt. Modeled ILO unemployment is an estimate. Annual releases can lag substantially. |
| Europe | 12 Eurostat and six ECB series | Current HICP uses `prc_hicp_minr`, ECOICOP 2 and EA21. Old HICP returned plausible December 2025 data, so a successful HTTP response alone was insufficient. |
| Regional statistics | ABS, SingStat, IBGE, BCB, BIS, OECD | Pinned series/dimensions and captured response fixtures. Coverage is deliberately narrow. ABS CPI uses the September 2025 base. |
| Environment | 45 Open-Meteo series; four NWS state feeds | Forecast, reanalysis and air-quality model output remain distinct. NWS events are not numerical quotes. Open-Meteo free access has non-commercial conditions. |
| Markets | Yahoo, Frankfurter, CoinGecko | Existing keyless price coverage. Quote timestamps describe market observations; closed markets are not judged against a universal 60-second age. |
| Optional US economics | FRED, BLS, BEA | Kept out of the keyless starter. Credential-dependent live qualification is not established by fixture tests. FRED mirrors retain original publisher families. |

Raw receipts in this directory preserve failed probes as well as corrected
follow-ups. Fixtures in `tests/fixtures/data_desk/` retain source responses and
request identities. Retrieval time never substitutes for missing publication time.
Revision policy is explicit; displaying latest revisions does not prove first-release
values suitable for a historical forecasting trial.

## Conditional expansion

These sources are researched candidates, not working starter entries:

- **IMF DataMapper:** the endpoint returned HTTP 403 in this environment. Parser
  reuse is implemented, but no curated rows are exposed until access is qualified.
- **Japan e-Stat:** [official API instructions](https://www.e-stat.go.jp/api/api/api/index.php/en/api-dev/how_to_use)
  require a registered application ID. Admission needs a fixed statistical table,
  classification dimensions and units, plus credentialed replay evidence.
- **Mexico INEGI:** [official API guide](https://en.www.inegi.org.mx/servicios/api_indicadores.html)
  requires a token. Bind indicator, geography, unit and multiplier. Indicator
  `LASTUPDATE` must not be advertised as each observation's publication time.
- **Saudi SAMA:** the [API manual](https://www.sama.gov.sa/ar-sa/Publications/EconomicReports/Documents/UserManual.pdf)
  documents `GetStatistcalById`. A reproducible portal query ID and column/row
  interpretation are still needed before admitting a measurement.
- **UAE:** [CBUAE statistics](https://centralbank.ae/en/research-and-statistics/latest-statistics/)
  provide publications; this review did not establish a stable public numeric
  API with sufficient measurement metadata.
- **Direct African national feeds:** publication repositories, including the
  [KNBS repository](https://repository.knbs.or.ke/), do not by themselves establish
  a qualified numeric adapter. Initial regional breadth uses World Bank country
  indicators. Dedicated national-source qualification remains future expansion.

## Freshness policy

Retrieval cadence is separate from observation age. Catalog entries with an
explicit expected lag are checked against the latest nonmissing observation's
period end, including cached responses. Expired forecast windows are flagged.
A warning retains useful data; it does not replace it with zero or silently select
another series. Entries without a qualified lag do not invent a release schedule.
