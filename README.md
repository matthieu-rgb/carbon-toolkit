<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# CARBON

Containerized automotive pentest toolkit: a CLI (and TUI, Web, and MCP clients)
that drives a CAN bus and speaks UDS (ISO 14229) through a registry of tools,
with an authorization guard for destructive actions and an append-only audit
journal. Licensed GPL-3.0-or-later.

## Documentation

- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture and design reference (English).
- [`docs/GUIDE.md`](docs/GUIDE.md) — guide complet d'utilisation (français) : installation, concepts, parcours CAN/UDS, mode Guidé, mode Web, pilotage par IA.

## Install

### From source (Python >= 3.11)

    python3 -m venv .venv && . .venv/bin/activate
    pip install -e '.[dev]'
    pytest            # no hardware needed (python-can `virtual` bus)

### Docker image (x86_64 and ARM64)

    docker buildx build --platform linux/amd64,linux/arm64 -t carbon:0.6.0 .   # multi-arch (needs a registry or --push)
    docker buildx build --load -t carbon:0.6.0 .                               # host arch only, into the local daemon

The image bundles `carbon`, python-can and `can-utils`. It runs unprivileged
and does not need `--privileged`.

## Quickstart

Run `carbon` with no command for a dashboard: the current bus, your recent
actions, and the suggested next step. In an interactive terminal, tool results
print as readable panels; piped or scripted output stays a plain summary line.

Real CAN needs Linux. Create a virtual bus on the host (root, `vcan` module):

    sudo scripts/setup_vcan.sh vcan0

Run the container on the host network so it sees `vcan0` (a socketcan socket needs no extra capability):

    docker run --rm --network host -v "$PWD:/work" carbon:0.6.0 can_sniff --count 5
    docker run --rm --network host -v "$PWD:/work" carbon:0.6.0 can_dump capture.log --count 100
    docker run --rm --network host -v "$PWD:/work" carbon:0.6.0 --yes can_replay capture.log
    docker run --rm --network host -v "$PWD:/work" carbon:0.6.0 --yes can_inject 7DF 0201

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

    docker run --rm carbon:0.6.0 smoke        # in the image
    bash scripts/smoke_can_cycle.sh            # on a host where `carbon` is on PATH

Bus selection is automatic: `vcan0` over socketcan when `scripts/setup_vcan.sh`
succeeds (Linux with root and the `vcan` module, e.g. `--user root --cap-add NET_ADMIN`),
otherwise python-can's `udp_multicast` bus (loopback, works unprivileged on
macOS and in the container). Override with `CARBON_SMOKE_INTERFACE` and `CARBON_SMOKE_CHANNEL`.

## UDS / simulated ECU

CARBON ships a UDS client (udsoncan over ISO-TP via can-isotp, pure Python) and a
simulated ECU to practice on safely: no real vehicle needed. Tools:
`uds_scan`, `uds_session`, `uds_security_access`, `uds_read_did`,
`uds_read_dtc`, `uds_clear_dtc`; the ECU is `carbon emu start`
(see `carbon --help`).

### Run the ECU, then talk to it

Terminal 1 (the ECU listens on request id 0x7E0, answers on 0x7E8):

    carbon --channel vcan0 emu start

Terminal 2, the typical dialogue (scan -> session -> seed-key -> DID -> DTC):

    carbon --channel vcan0 uds_scan                     # which services answer
    carbon --channel vcan0 uds_read_did F190            # VIN (open): 434152424f4e53494d4543553030303031
    carbon --channel vcan0 uds_read_did 1234            # protected: refused, NRC 0x33 (locked)
    carbon --channel vcan0 uds_session                  # extended diagnostic session
    carbon --channel vcan0 uds_security_access          # seed -> key -> unlocked
    carbon --channel vcan0 uds_read_did 1234            # now succeeds: deadbeef
    carbon --channel vcan0 uds_read_dtc                 # 2 DTCs stored
    carbon --channel vcan0 --yes uds_clear_dtc          # destructive: --yes required
    carbon --channel vcan0 uds_read_dtc                 # 0 DTC

`uds_clear_dtc` is destructive: it asks for interactive confirmation, and
refuses to run non-interactively unless `--yes` (a global option, placed before
the subcommand) is given. Every run is written to the journal.

### The example seed-key algorithm

SecurityAccess is a challenge/response: the tool asks for a seed
(`requestSeed`), computes a key and sends it back (`sendKey`). The simulated
ECU uses a documented educational algorithm (not a real manufacturer one), so
you can reproduce it by hand:

    key = rotl32(seed XOR 0xA5A5A5A5, 3)

i.e. XOR the 4-byte seed with `A5A5A5A5`, then rotate the 32-bit result left by
3 bits. Example: seed `11223344` -> key `a43cb70d`.

    python3 -c "s=0x11223344^0xA5A5A5A5; print(f'{((s<<3)|(s>>29))&0xFFFFFFFF:08x}')"

The implementation is `carbon/uds/seedkey.py` (`ExampleSeedKey`); the framework
accepts other algorithms implementing `key_from_seed(seed) -> key`.

### Real vcan0 vs no hardware

- Linux with `vcan0` (see Quickstart): use `--channel vcan0` as above; run the
  ECU and the tools in containers with `--network host`, e.g.
  `docker run --rm --network host carbon:0.6.0 emu start`.
- No Linux/vcan (macOS, plain container): use a python-can emulated bus that is
  shared across processes, e.g. `--interface udp_multicast --channel 239.74.163.3`
  on both the ECU and the tools (the in-process `virtual` bus cannot be shared
  between separate `carbon` commands).
- A real ECU: point `--interface`/`--channel` at your adapter
  (`can0`, slcan...). Only test vehicles and ECUs you are authorized to test.

### UDS smoke test

`scripts/smoke_uds_cycle.sh` starts the ECU in the background, polls until it
answers, runs the dialogue above asserting every outcome (>= 5 services, VIN,
locked DID refused, unlock, DID readable, 2 DTCs, clear, 0 DTC), stops the ECU,
and prints `cycle UDS OK` (exit 0) or fails (exit != 0). Bus selection is the
same as for the CAN smoke test.

    docker run --rm --user root --cap-add NET_ADMIN --network host carbon:0.6.0 smoke-uds   # vcan0 in the image
    docker run --rm carbon:0.6.0 smoke-uds                                                    # udp_multicast fallback
    bash scripts/smoke_uds_cycle.sh                                                          # host with `carbon` on PATH

## Driving CARBON over MCP

CARBON exposes its tools to an AI client over the Model Context Protocol:
`carbon mcp serve`. The same guards as the CLI apply (registry, authorization,
journal): the server adds no execution path.

### stdio (Claude Desktop and similar clients)

    carbon --channel vcan0 --interface socketcan mcp serve --transport stdio

Typical client config: `{"mcpServers": {"carbon": {"command": "carbon",
"args": ["--channel", "vcan0", "mcp", "serve", "--transport", "stdio"]}}}`.
In stdio the console is the protocol pipe, so there is no approval channel and
**every destructive action is refused**.

### HTTP + Bearer token

    carbon --channel vcan0 mcp serve --transport http --port 8777

The server binds `127.0.0.1` only, endpoint `/mcp`. A random Bearer token is
generated at each launch and written outside the repository (`$XDG_RUNTIME_DIR`
or the temp dir, mode 0600); only the file **path** is printed. Every request
must carry `Authorization: Bearer <token>`, otherwise 401.

### Destructive actions: approval at the server console

Over HTTP, a destructive action (`can_replay`, `can_inject`, `uds_clear_dtc`)
is held (`pending-approval`). The operator approves it **at the server console**
(never the AI): `list`, `approve <id>`, `deny <id>`. With no answer, the action
times out and is refused. Everything is journaled.

### Smoke test

    bash scripts/smoke_mcp.sh                 # or: docker run --rm carbon:0.6.0 smoke-mcp

The smoke runs the simulated ECU and an in-memory MCP client (lists tools, calls
`uds_scan`, reads `session_state` and the `carbon://journal` resource, holds a
destructive action then approves it).

## Guided mode (terminal UI)

CARBON ships a guided walkthrough: a declarative methodology engine
(`carbon/methodology/trees/carbon_v1.yaml`) and a Textual UI that walk the
CAN/UDS phases 1 to 6 (access, CAN reconnaissance, UDS discovery and session,
DTC read, seed-key, clear, replay, injection).

    carbon tui --methodology carbon/methodology/trees/carbon_v1.yaml

With no hardware, the walkthrough runs on `vcan0` (or the virtual bus) with the
simulated ECU (see "UDS / simulated ECU"). At each step the TUI shows the goal,
the expected tool and the result; the next step unlocks only once the step's
condition is met. In Guided mode a tool outside the walkthrough is refused;
Libre mode stays available.

Destructive steps (`uds_clear_dtc`, `can_replay`, `can_inject`) always go
through approval: the TUI opens a modal the operator accepts or rejects, the
guard stays intact, and everything is journaled. The walkthrough position is
saved and resumed on relaunch.

### Guided smoke test

    bash scripts/smoke_guided.sh                 # or: docker run --rm carbon:0.6.0 smoke-guided

The smoke exercises the engine (without the TUI) on the simulated ECU: it walks
steps 1 to 6, approves destructive actions from a thread, checks the final step
and the resume of persisted state, and prints `smoke GUIDED OK`.

## Web mode / attack-surface map

`carbon web` serves a local Web client: a live attack-surface map built from the
session history, and click-to-run Libre mode. It is the same core as the TUI and
MCP (same `Session`, tool registry, approval queue and journal). Guided mode
stays in the TUI for now; the Web client is Libre only.

    carbon web                       # 127.0.0.1:8800
    carbon --interface virtual --channel carbon-demo web --port 8800

The command prints a single-use bootstrap link,
`http://127.0.0.1:<port>/?k=<web-token>`, and the path of the MCP token file
(MCP is still served under `/mcp`). Opening the link sets the `carbon_web`
cookie (HttpOnly, SameSite=Strict) and redirects (303) to `/`; the token no
longer appears in the URL afterwards.

Security posture:

- binds `127.0.0.1` only (any other address is refused);
- the Web token is distinct from the MCP Bearer token: the cookie grants no
  access to `/mcp`, and vice versa;
- `HttpOnly` + `SameSite=Strict` cookie; `Host`/`Origin` checks (unsafe
  requests require a same-origin `Origin`, 403 otherwise);
- destructive actions (`uds_clear_dtc`, `can_replay`, `can_inject`) require
  human approval in the Web modal (AC-10): a click on the tool is not enough,
  and everything is journaled.

### Web smoke test

    bash scripts/smoke_web.sh                    # or: docker run --rm carbon:0.6.0 smoke-web

With no browser or curl: it starts `carbon web` on a virtual channel, follows
the bootstrap link, checks that `/api/state` is refused without the cookie then
returns `surface` and `tools` with it, that the link is single-use and that the
Web cookie does not open `/mcp`, then prints `WEB OK`.
