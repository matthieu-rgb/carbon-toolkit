#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Smoke test of the CAN cycle: dump + replay + inject --yes, then verify.
#
# Modes (auto-selected, override with CARBON_SMOKE_INTERFACE / CARBON_SMOKE_CHANNEL):
#   * Linux with vcan (in the container, or a host with root): runs
#     scripts/setup_vcan.sh then drives --interface socketcan --channel vcan0.
#   * Otherwise (macOS host, container without vcan): drives python-can's
#     `udp_multicast` interface (a CAN bus emulated over loopback multicast,
#     shared across processes -- the plain `virtual` interface is in-process
#     only, so separate `carbon` invocations could not see each other).
# Exit 0 and prints "cycle CAN OK" on success, non-zero otherwise.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$WORK"' EXIT
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

command -v carbon >/dev/null 2>&1 || fail "carbon CLI not found on PATH"

IFACE="${CARBON_SMOKE_INTERFACE:-}"
CHAN="${CARBON_SMOKE_CHANNEL:-}"
if [ -z "$IFACE" ]; then
    if [ "$(uname -s)" = "Linux" ] && bash "$HERE/setup_vcan.sh" vcan0 >/dev/null 2>&1; then
        IFACE=socketcan; CHAN="${CHAN:-vcan0}"
    else
        IFACE=udp_multicast; CHAN="${CHAN:-239.74.163.2}"
    fi
fi
CHAN="${CHAN:-vcan0}"
echo "smoke: interface=$IFACE channel=$CHAN"

C=(carbon --interface "$IFACE" --channel "$CHAN" --journal "$WORK/journal.jsonl")

# Seed capture (candump -l format): 2 standard frames + 1 extended frame.
cat > "$WORK/seed.log" <<LOG
(1700000000.000000) $CHAN 123#DEADBEEF
(1700000000.010000) $CHAN 456#0102030405060708
(1700000000.020000) $CHAN 18DAF110#AA55
LOG

# Run a dump in background, wait until it is listening, then run "$@" to
# generate traffic, then wait for the dump to finish.
capture_while() { # capture_while OUT COUNT -- command...
    local out="$1" count="$2"; shift 3
    "${C[@]}" can_dump "$out" --count "$count" --timeout 10 >"$WORK/dump.out" 2>&1 &
    local pid=$!
    sleep 2
    "$@" >"$WORK/traffic.out" 2>&1 || { cat "$WORK/traffic.out" >&2; fail "traffic command failed: $*"; }
    wait "$pid" || { cat "$WORK/dump.out" >&2; fail "can_dump failed"; }
}

# 1. replay --yes while dumping -> the dump must hold exactly the seed frames.
capture_while "$WORK/replayed.log" 3 -- "${C[@]}" --yes can_replay "$WORK/seed.log"
for f in "123#DEADBEEF" "456#0102030405060708" "18DAF110#AA55"; do
    grep -q " ${f}$" "$WORK/replayed.log" || fail "replayed frame $f missing from dump"
done

# 2. inject --yes while dumping -> the dump must hold the forged frame.
capture_while "$WORK/injected.log" 1 -- "${C[@]}" --yes can_inject 7DF 0201 
grep -q " 7DF#0201$" "$WORK/injected.log" || fail "injected frame 7DF#0201 missing from dump"

# 3. destructive command without --yes must be refused (non-interactive guard).
if "${C[@]}" can_inject 7DF 00 </dev/null >/dev/null 2>&1; then
    fail "inject without --yes was not refused"
fi

# 4. journal must record the destructive actions.
grep -q can_replay "$WORK/journal.jsonl" && grep -q can_inject "$WORK/journal.jsonl" \
    || fail "journal lacks replay/inject entries"

echo "cycle CAN OK"
