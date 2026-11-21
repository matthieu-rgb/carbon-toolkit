#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Smoke test of the UDS cycle against the simulated ECU:
#   scan -> read VIN -> protected DID refused -> seed-key unlock -> protected
#   DID readable -> read DTCs -> clear DTCs (--yes) -> no DTC left.
#
# Bus selection mirrors scripts/smoke_can_cycle.sh (override with
# CARBON_SMOKE_INTERFACE / CARBON_SMOKE_CHANNEL):
#   * Linux with vcan: scripts/setup_vcan.sh, then socketcan on vcan0.
#   * Otherwise: python-can `udp_multicast` (shared across processes, unlike
#     the in-process `virtual` interface).
# Exit 0 and prints "cycle UDS OK" on success, non-zero otherwise.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
ECU_PID=""
cleanup() {
    if [ -n "$ECU_PID" ]; then
        kill "$ECU_PID" 2>/dev/null || true
        wait "$ECU_PID" 2>/dev/null || true
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

command -v carbon >/dev/null 2>&1 || fail "carbon CLI not found on PATH"

IFACE="${CARBON_SMOKE_INTERFACE:-}"
CHAN="${CARBON_SMOKE_CHANNEL:-}"
if [ -z "$IFACE" ]; then
    if [ "$(uname -s)" = "Linux" ] && bash "$HERE/setup_vcan.sh" vcan0 >/dev/null 2>&1; then
        IFACE=socketcan; CHAN="${CHAN:-vcan0}"
    else
        IFACE=udp_multicast; CHAN="${CHAN:-239.74.163.3}"
    fi
fi
CHAN="${CHAN:-vcan0}"
echo "smoke: interface=$IFACE channel=$CHAN"

C=(carbon --interface "$IFACE" --channel "$CHAN" --journal "$WORK/journal.jsonl")

# Run the ECU in the background.
"${C[@]}" emu start >"$WORK/emu.out" 2>&1 &
ECU_PID=$!

# Bounded readiness polling: the ECU is ready once a scan succeeds.
READY=0
for _ in $(seq 1 30); do
    kill -0 "$ECU_PID" 2>/dev/null || { cat "$WORK/emu.out" >&2; fail "ECU process died"; }
    if "${C[@]}" uds_scan >"$WORK/scan.out" 2>&1; then READY=1; break; fi
    sleep 0.5
done
[ "$READY" = 1 ] || { cat "$WORK/emu.out" "$WORK/scan.out" >&2; fail "ECU not ready within timeout"; }

# step LABEL RC -- args...: run a carbon command, store its output in $OUT and
# its exit code in $RC (never aborts: assertions decide).
step() {
    local label="$1"; shift
    RC=0
    OUT="$("${C[@]}" "$@" 2>&1)" || RC=$?
    echo "[$label] rc=$RC: $OUT"
}
expect_ok() { [ "$RC" -eq 0 ] || fail "$1: expected success, got rc=$RC"; }
expect_refused() { [ "$RC" -ne 0 ] || fail "$1: expected refusal, got success"; }
expect_match() { printf '%s\n' "$OUT" | grep -Eq "$2" || fail "$1: output does not match /$2/"; }

# 1. scan: at least 5 supported services.
step scan uds_scan
expect_ok scan
N="$(printf '%s\n' "$OUT" | sed -n 's/^\([0-9][0-9]*\) of .*/\1/p')"
[ -n "$N" ] && [ "$N" -ge 5 ] || fail "scan: expected >= 5 services, got '${N:-none}'"

# 2. VIN (DID F190) readable without unlocking: hex of CARBONSIMECU00001.
step vin uds_read_did F190
expect_ok vin
expect_match vin '434152424f4e53494d4543553030303031'

# 3. protected DID 1234 is refused while locked.
step locked uds_read_did 1234
expect_refused locked
expect_match locked 'NRC 0x33'

# 4. extended session + seed-key unlock.
step session uds_session --session extended
expect_ok session
step unlock uds_security_access
expect_ok unlock
expect_match unlock 'unlocked'

# 5. the protected DID now succeeds.
step unlocked uds_read_did 1234
expect_ok unlocked
expect_match unlocked 'DID 0x1234 = '

# 6. two DTCs stored.
step dtc uds_read_dtc
expect_ok dtc
expect_match dtc '^2 DTC\(s\) read'

# 7. clear needs --yes (destructive); refused without it, accepted with it.
if "${C[@]}" uds_clear_dtc </dev/null >/dev/null 2>&1; then
    fail "clear without --yes was not refused"
fi
step clear --yes uds_clear_dtc
expect_ok clear
expect_match clear 'cleared'

# 8. no DTC left.
step dtc-after uds_read_dtc
expect_ok dtc-after
expect_match dtc-after '^0 DTC\(s\) read'

# 9. journal records the destructive clear.
grep -q uds_clear_dtc "$WORK/journal.jsonl" || fail "journal lacks uds_clear_dtc entry"

echo "cycle UDS OK"
