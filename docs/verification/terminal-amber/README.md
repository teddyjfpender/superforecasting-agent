# Terminal Amber

A built-in financial-terminal palette: black canvas, amber navigation and labels,
neutral white data, cyan information, and distinct green/red changes. It is an
independent Superforecasting Agent theme, not a Bloomberg product or affiliation.

## Activate

In the TUI, open `/theme` and choose **Terminal Amber**. The classic CLI accepts
`/skin terminal-amber`. For persistent configuration:

```yaml
display:
  skin: terminal-amber
```

The theme paints its own black canvas, including on terminals advertising a light
background. Existing themes retain their previous background behavior.

## Measured contrast

Ratios use WCAG relative luminance on the actual palette consumed by the TUI.
[WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum)
requires 4.5:1 for ordinary text at AA; AAA uses 7:1.

| Role | Color | Black canvas | Selected row `#172433` |
| --- | --- | ---: | ---: |
| Text | `#F5F5F5` | 19.26:1 | 14.41:1 |
| Muted text | `#B8B8B8` | 10.59:1 | 7.92:1 |
| Amber | `#FFB347` | 11.79:1 | 8.82:1 |
| Information | `#66D9EF` | 12.74:1 | 9.53:1 |
| Positive | `#76E69D` | 13.58:1 | 10.16:1 |
| Negative | `#FF9696` | 10.05:1 | 7.52:1 |
| Warning | `#FFE066` | 16.11:1 | 12.05:1 |
| Border / faint text | `#A3A3A3` | 8.33:1 | 6.23:1 |

`terminalAmber.test.ts` enforces 7:1 for substantive text across canvas, selection,
status and completion backgrounds, and 4.5:1 for borders also used as faint text.
A Python test keeps its fixture synchronized with the canonical skin definition.
These are palette checks, not a claim of whole-application WCAG conformance:
terminal font rendering, color remapping and dim attributes can affect appearance.
Changes also retain signs/arrows, so color is not the sole signal.

## Rendering and data checks — 2026-09-15

Reviewed real Ink Markets frames at 120×40 and 80×24 using a controlled gateway
with public source readings. The narrow layout retains NAME, LAST and CHG;
comparison dates remain at the top of the detail pane without overlapping text.
This is component rendering evidence, not native cross-platform qualification.

A read-only audit returned 200 numeric quotes across 14 provider groups. Thirteen
had equal latest observations: five stepwise policy targets, four FRED series and
four Eurostat unemployment series. Live backfills now expose observed policy
moves for Brazil, the US, UK, Japan and South Africa. Ordinary equal reporting
periods still show zero, with last movement separately when supported by history.
Tiny nonzero changes retain precision instead of appearing as `0.0000`.

See [provider comparison rules](../../../forecasting/marketdata/providers/README.md#change-references)
for source semantics and bounded acquisition limits.
