#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Entrypoint: `smoke` runs the CAN cycle smoke test, `smoke-uds` the UDS cycle
# smoke test, `shell` opens bash, anything else is passed to the `carbon` CLI.
set -euo pipefail

case "${1:-}" in
    smoke) exec bash /opt/carbon/scripts/smoke_can_cycle.sh ;;
    smoke-uds) exec bash /opt/carbon/scripts/smoke_uds_cycle.sh ;;
    shell) shift; exec bash "$@" ;;
    *)     exec carbon "$@" ;;
esac
