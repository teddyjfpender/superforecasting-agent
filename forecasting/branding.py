"""Product identity for the forecasting fork."""

PRODUCT_NAME = "Superforecasting Agent"
PRODUCT_SLUG = "superforecasting-agent"
CLI_SURFACE = "forecast"
DESK_TITLE = "SUPERFORECASTING DESK"
CORE_PRIMITIVE = "forecast"
NORTH_STAR = "A command-line forecasting desk that compounds judgment over time."
FORK_CONTEXT_DOC = "docs/plans/2026-05-20-superforecasting-agent-fork-context.md"
FORK_PRD_DOC = "docs/plans/2026-05-20-superforecasting-agent-fork-prd.md"

KEEP_SURFACES = [
    "CLI/TUI runtime",
    "tool registry",
    "provider routing",
    "local storage",
    "cron scheduler",
]

DEMOTED_SURFACES = [
    "gateway-first messaging",
    "general assistant branding",
    "generic chat memory",
    "broad do-anything tool exposure",
]
