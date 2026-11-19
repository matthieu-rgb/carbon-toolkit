#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Create and bring up a virtual CAN interface (default: vcan0). Idempotent.
# Requires root (modprobe / ip link): run with sudo. Linux only.
set -euo pipefail

IFACE="${1:-vcan0}"

modprobe vcan
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    ip link add dev "$IFACE" type vcan
fi
ip link set up "$IFACE"
echo "$IFACE is up"
