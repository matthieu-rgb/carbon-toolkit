<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# CARBON

Containerized automotive pentest toolkit (v0.1 "socle"): a CLI that drives a
CAN bus through a registry of tools, with an authorization guard for
destructive actions and an append-only audit journal. Licensed GPL-3.0-or-later.

## Install

### From source (Python >= 3.11)

    python3 -m venv .venv && . .venv/bin/activate
    pip install -e '.[dev]'
    pytest            # 30 tests, no hardware needed (python-can `virtual` bus)

### Docker image (x86_64 and ARM64)

    docker buildx build --platform linux/amd64,linux/arm64 -t carbon:0.1.0 .   # multi-arch (needs a registry or --push)
    docker buildx build --load -t carbon:0.1.0 .                               # host arch only, into the local daemon

The image bundles `carbon`, python-can and `can-utils`. It runs unprivileged
and does not need `--privileged`.

## Quickstart

Real CAN needs Linux. Create a virtual bus on the host (root, `vcan` module):

    sudo scripts/setup_vcan.sh vcan0

Run the container on the host network so it sees `vcan0` (a socketcan socket needs no extra capability):

    docker run --rm --network host -v "$PWD:/work" carbon:0.1.0 can_sniff --count 5
    docker run --rm --network host -v "$PWD:/work" carbon:0.1.0 can_dump capture.log --count 100
    docker run --rm --network host -v "$PWD:/work" carbon:0.1.0 --yes can_replay capture.log
    docker run --rm --network host -v "$PWD:/work" carbon:0.1.0 --yes can_inject 7DF 0201

Global options go before the subcommand: `--channel` (default `vcan0`),
`--interface` (default `socketcan`), `--journal` (default `carbon-session.jsonl`),
`--yes`. `can_replay` and `can_inject` are destructive and refuse to run
non-interactively without `--yes`. Every run is recorded in the journal.

Without Linux/vcan, use python-can's emulated buses, e.g. `--interface udp_multicast --channel 239.74.163.2`.

### Flags for real hardware (instead of `--privileged`)

| Need | Flags |
|------|-------|
| Existing host `vcan0`/`can0` | `--network host` |
| Create vcan inside the container | `--user root --cap-add NET_ADMIN --network host` (then `scripts/setup_vcan.sh`) |
| USB CAN adapter (slcan, gs_usb...) | `--device /dev/ttyACM0` (or the relevant node) |
| DoIP (Ethernet to the ECU) | `--network host` or a macvlan network, plus `--cap-add NET_RAW` if raw sockets are used |

None of these are needed for the virtual bus used by the tests.

## Smoke test

`scripts/smoke_can_cycle.sh` exercises the whole cycle: replays a capture
while `can_dump` records it, injects a frame, checks that a destructive command
without `--yes` is refused and that the journal has entries, then prints
`cycle CAN OK` (exit 0) or fails (exit != 0).

    docker run --rm carbon:0.1.0 smoke        # in the image
    bash scripts/smoke_can_cycle.sh            # on a host where `carbon` is on PATH

Bus selection is automatic: `vcan0` over socketcan when `scripts/setup_vcan.sh`
succeeds (Linux with root and the `vcan` module, e.g. `--user root --cap-add NET_ADMIN`),
otherwise python-can's `udp_multicast` bus (loopback, works unprivileged on
macOS and in the container). Override with `CARBON_SMOKE_INTERFACE` and `CARBON_SMOKE_CHANNEL`.
