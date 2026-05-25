#!/bin/bash
# Compatibility wrapper for existing docs, scripts, and local checkouts.
# Prefer ./setup-superforecasting-agent.sh for new Superforecasting Agent installs.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/setup-superforecasting-agent.sh" "$@"
