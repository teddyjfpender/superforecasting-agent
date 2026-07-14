# Change-control schemas

These checked-in schemas are the stable wire contracts shared by the ledger,
Slack transport, and GitHub projection. Files are versioned rather than edited
in place after release. Canonical digests use UTF-8 JSON with sorted keys, no
insignificant whitespace, and no NaN/Infinity values, as implemented by
`forecasting.change_control.models.canonical_json`.
