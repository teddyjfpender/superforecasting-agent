# Data-desk source fixtures

These small public API responses were captured on 14–15 September 2026 through the
same adapters used by the data desk. Each file records the requested series,
public request URL, capture time, catalog revision, raw response, and expected
latest value and history length. The refreshed BCB/BIS captures also pin the
source periods and values used for the last policy-rate transition. They contain no credentials.

The replay tests in
[`test_data_desk_source_fixtures.py`](../../forecasting/test_data_desk_source_fixtures.py)
exercise real provider adapters without networking. Synthetic adversarial cases
in [`test_data_desk_sources.py`](../../forecasting/test_data_desk_sources.py)
change dimensions, units, periods, and identities to prove that plausible wrong
measurements are rejected.

Capture time is test provenance, not an observation's publication time. These
samples do not authorize forecast settlement, guarantee continuing availability,
or qualify every series offered by a provider. Live qualification receipts are
kept separately in [`docs/verification/data-desk`](../../../docs/verification/data-desk/README.md).
