<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# CARBON — Design

This document explains how CARBON is built and why. It is the architectural
reference for contributors: what the pieces are, the invariants that hold them
together, and the decisions behind them. For installation and day-to-day use,
see the [README](../README.md) (English) and the
[Guide complet en français](GUIDE.md).

---

## 1. Purpose

Automotive security tools (`can-utils`, Scapy/ISO-TP, `udsoncan`, and the rest)
exist but are scattered: each installs its own way and assumes the operator
already knows where they are in the assessment. CARBON fills that gap — a
single, reproducible, disposable Docker environment (*"an Exegol for cars"*)
that **integrates** the best tools rather than rewriting them, and adds a
**piloting layer** that keeps the operator located in the vehicle's attack
surface at all times.

Two choices shape everything else:

- CARBON exposes its core as an **MCP server** (Model Context Protocol), so the
  piloting layer is **drivable by any AI** — a local model (Ollama, llama.cpp)
  or a frontier one — without CARBON embedding or mandating any model.
- The network scope covers **CAN** today and reaches toward **Automotive
  Ethernet** (DoIP, with SOME/IP as a later extension).

CARBON serves **two audiences at once**: a beginner *discovers* automotive
pentesting with it (Guided mode, an explanatory UI), and an expert *uses it for
real work* (Libre mode — fast, dense, no friction). It is a professional tool
with a gentle on-ramp, not a teaching toy and not an expert-only CLI.

---

## 2. Goals and non-goals

**Goals**

| # | Goal | Indicator |
|---|------|-----------|
| O1 | Frictionless start | Operational in < 5 min on a clean Docker host |
| O2 | Reference CAN/UDS coverage | Common CAN/UDS operations done without leaving CARBON |
| O3 | Reproducibility | Two installs → identical environment (versioned image) |
| O4 | Pedagogy | A beginner always knows the next step in Guided mode |
| O5 | Field portability | Same image on x86 laptop and ARM (Raspberry Pi) |
| O6 | Pluggable, model-agnostic AI | A local **and** a frontier model drive a session over MCP, no CARBON code change |
| O7 | Two UIs, one core | TUI and Web offer the same actions; the logic is written once |

**Non-goals (v1)**: rewriting upstream tools (we integrate, we don't reimplement);
advanced binary firmware analysis; a native mobile UI; a turnkey embedded AI
agent (a scoped extension, not core).

**Anti-goals** (what would make the project a failure even if it "works"): yet
another tool aggregate with no layer that locates the operator; a piloting layer
that contains tool logic, or tools that contain methodology (the decoupling is
broken); a product bound to a single AI model; any capability designed for
unauthorized use on a third-party vehicle.

---

## 3. The golden rule

> **The methodology engine contains no tool; the tool registry contains no
> methodology. Either can be replaced without breaking the other.**

A corollary governs execution:

> **Single execution path.** Every tool run — from the CLI, the TUI, the Web
> client or an MCP client — goes through `Session.run_tool` → `execute_tool`.
> The methodology engine and the attack-surface projection execute nothing;
> they only read results and annotate state. There is no path that reaches a
> tool while bypassing the authorization guard and the journal.

These two invariants are what the whole architecture protects.

---

## 4. Architecture

```
        CLIENTS (operator's choice)                     [no AI: manual piloting]
   +------------------+------------------+------------------------+
   | TUI (terminal)   | Web (browser)    | External MCP client    |
   | Textual          | Starlette + JS   | Claude Desktop, Cursor  |
   +--------+---------+--------+---------+-----------+------------+
            |  in-process API  |             |  MCP (HTTP + token)  |
            v                  v             v
   +=================================================================+
   |                           CARBON CORE                           |
   |  +--------------------------+   +----------------------------+   |
   |  | METHODOLOGY ENGINE       |   | TOOL REGISTRY (adapters)   |   |
   |  | YAML attack tree, session|<->| can_sniff/replay/inject,   |   |
   |  | state, position, progress|   | uds_scan/session/sec_access|   |
   |  +--------------------------+   | read_did/read_dtc/clear_dtc|   |
   |  +--------------------------+   +----------------------------+   |
   |  | AUDIT JOURNAL (append-   |   | MCP SERVER (localhost +    |   |
   |  | only) + approval queue   |   | Bearer token)              |   |
   |  +--------------------------+   +----------------------------+   |
   +=================================================================+
                                  |
                        HARDWARE ACCESS LAYER
              SocketCAN (can0 / vcan0), USB passthrough, DoIP/IP
                                  |
   +------------------+------------------+---------------------------+
   | x86 host (CAN)   | ARM probe (Pi)   | virtual CAN (labs/tests)  |
   +------------------+------------------+---------------------------+
```

### 4.1 The core

A single Python library, used in-process by the TUI and the Web client and
exposed by the MCP server. It owns session state, position in the attack
surface, tool execution through adapters, the journal, and (roadmap) report
generation. The MCP server, the TUI and the Web client are **thin clients over
one shared `Session` instance** running in one process — which is exactly what
lets a destructive action requested by an AI over MCP pop up **immediately** for
human approval in the TUI or the Web client.

### 4.2 Tool registry (adapters)

Each integrated tool is wrapped by an **adapter** with a uniform interface:
validated inputs, a **structured result** (`ToolResult`), a return code,
artifacts. Adapters call upstream libraries (`python-can`, `can-utils`,
`udsoncan`, …) — they do not reimplement them. Adding a tool is declarative and
documented.

The structured-output contract is a first-class deliverable, not a detail:
progression and the position on the map are computed from `ToolResult` fields,
never from free-text parsing.

### 4.3 Methodology engine (declarative)

The attack tree is described in **YAML** (declarative, so it is contributable
and versioned in the repo). Each step declares: `id`, `title`, `objective`
(shown to the operator), an optional `tool` (a registry adapter, referenced by
name, plus default parameters — an informational step may have none and advance
on acknowledgement), `expected` text, `conditions` (machine-evaluable predicates
on the step's own `ToolResult`), and `next` candidate steps.

The engine is the **authority on progression**, in two moves:

- It **deterministically evaluates** the YAML conditions against the adapter's
  structured output. When a single branch is satisfied it may auto-advance, so
  progress stays reliable and testable **without any AI**.
- When several branches are possible or none is decisive, it **proposes** the
  candidate steps and lets the **operator or the AI choose**; the choice is
  journaled. The AI interprets and explains, but never redefines the map.

**Condition grammar — closed and flat.** `ok` (top level) plus
`equals(path, v)`, `contains(path, v)`, `exists(path)`, `truthy(path)`,
combinable with `all`/`any`. `path` addresses a single level under `data`
(`data.<key>`) — no deep indexing, no arbitrary code. This is enough for the
step tree and is trivial and safe to evaluate. Branch selection uses an optional
`when` predicate on each `next` edge, evaluated against the result just produced.

**Two modes.** *Guided*: the engine holds the thread and enforces step order; a
tool that is neither the current step nor a candidate is refused (a
non-destructive, informative refusal that keeps a beginner on the rails).
*Libre*: direct access to every tool; the engine **traces** the position on the
map and **suggests** non-blockingly. Switching Guided ↔ Libre keeps the step
pointer verbatim — **no loss of state**.

**Persistence.** Session state (loaded methodology, current step, mode, history
of crossed steps and their `ToolResult`s) is serialized to JSON next to the
journal by atomic replacement on each transition, and resumed on restart. Resume
restores the **methodology position, not the live target state**: the simulated
ECU (a separate process) may have restarted and re-locked, so the engine does
not assume prerequisites still hold; replaying the step re-establishes them.

### 4.4 MCP server

Transport is **HTTP on `127.0.0.1` with a required Bearer token** by default,
with `stdio` as an option. It exposes three surfaces: **tools** (the adapters),
**methodology/state** (position, current step, suggestions, and the derived
attack surface), and **resources** (the raw journal; a formatted report is
roadmap). It is model-agnostic by construction — the model is supplied by the
client.

The server wraps the MCP SDK (`mcp==2.3.0`, API `MCPServer`) rather than
reimplementing it, and reaches tools **only** through the existing adapter
registry — no execution path parallel to the CLI.

### 4.5 Web client and attack-surface map

`carbon web` serves a localhost Web client in the **same process and the same
`Session`** as the MCP server, on one Starlette ASGI app: the MCP sub-app is
mounted under `/mcp` (Bearer-guarded) and the Web UI + API live under `/`
(cookie-guarded). It adds what the terminal cannot do:

- **A live attack-surface map** — a graph of bus → ECU → UDS services →
  security levels, with the current position highlighted, refreshed in real
  time. The map is a **pure derived projection**:
  `carbon/core/surface.py :: build_surface(history) -> dict` is a pure,
  monotonic fold of the `ToolResult` history into a graph, exposed under a
  `surface` key in `session.state()` — so the TUI, the Web client **and** MCP
  all read it with no duplicated logic. No methodology, no tool lives in that
  module: it is only a view.
- **Click-to-run Libre mode** — clicking a node/service sends an action to the
  core, which runs it through the single execution path. The Web client
  executes nothing itself.
- **A Web approval surface** for destructive actions (see §5).

Real-time transport is **SSE + POST**: the core pushes full `state()` snapshots
to the browser over Server-Sent Events (plus a periodic heartbeat); the browser
sends actions (run a tool, resolve an approval) by POST. The map is rendered
with vendored `cytoscape.js` (pinned, MIT, no CDN). The Web client is **Libre
only** for now; Guided stays in the TUI.

### 4.6 Simulated ECU

Real UDS practice needs a target that answers diagnostics. CARBON ships a
**simulated ECU** (`carbon emu start`): a small ISO-TP/UDS responder that handles
sessions, security access, DTC read/clear and a documented example seed-key
routine. It is the test fixture for the UDS layer and the reason everything can
run on a virtual bus with **no hardware**. It covers one ECU with correct
negative-response codes and real session/security locking — enough to make
sessions and seed-key meaningful without over-engineering a full fleet (a
multi-ECU lab is a later learning milestone).

The example seed-key is a documented educational transform, **not** real
manufacturer crypto: `key = rotl32(seed XOR 0xA5A5A5A5, 3)`. It plugs into a
pluggable seed-key framework (`key_from_seed(seed) -> key`) so other algorithms
can be supplied.

### 4.7 Hardware access layer

The container reaches the vehicle by targeted passthrough, never a blanket
`--privileged`: OBD-II → CAN USB adapters (SLCAN/gs_usb/native SocketCAN),
Automotive Ethernet/DoIP over IP, a USB Wi-Fi antenna in monitor mode, and a USB
BLE dongle — each via `--device`/`--cap-add` documented per device. When no
hardware is present, everything falls back to `vcan0` (Linux) or a python-can
emulated bus.

---

## 5. Security model

Security is a design property, not a feature bolted on:

- **Least privilege.** No global `--privileged` by default; targeted
  `--device`/`--cap-add` per device; `network=host` only where strictly required
  (DoIP) and documented.
- **Human approval of destructive actions (the central guarantee, AC-10).** Any
  action that can change an ECU's state (CAN injection, `clear_dtc`, UDS writes)
  goes through an **out-of-band human approval**. The action carries an
  **origin** (`CLI`, `MCP`, `TUI`, `WEB`). The CLI `--yes` auto-confirm is
  honored **only for a direct human CLI call**; it is **ignored for every
  non-CLI origin** — otherwise an AI holding the token would grant itself the
  action and empty the guarantee. A destructive action of non-CLI origin enters
  a blocking `pending-approval` queue and is executed only after an explicit
  human approval on a channel the AI cannot reach: the server console (MCP over
  HTTP), a TUI modal, or a Web modal. No approver responds → it times out and is
  refused (fail-closed). `stdio` MCP, where the console is the protocol pipe,
  simply refuses destructive actions for lack of a human channel.
- **MCP authentication.** Bearer token required by default, generated at launch,
  stored outside the repository (0600), bound to `127.0.0.1`.
- **Web authentication, distinct from MCP.** The Web token is **separate** from
  the MCP token: it is handed over via a single-use bootstrap URL (`/?k=<token>`)
  exchanged for an `HttpOnly` + `SameSite=Strict` session cookie. `Origin`/`Host`
  validation blocks CSRF and DNS-rebinding; all state-changing routes are POST.
  **Holding the MCP token grants no Web access** — it can neither drive the Web
  API nor resolve an approval — and vice versa.
- **Audit journal.** Every action (human or AI), timestamped, is appended to the
  journal so a session can be reconstructed.
- **Input validation** at every boundary (adapters, MCP API, Web API); no
  unparameterized shell execution from unvalidated input.
- **Secrets & privacy.** CARBON itself sends no mission data or operator identity
  to any external service. (Choosing a frontier model on the client side is
  outside CARBON's scope and documented as a caution.)
- **Legal frame.** ISO 21434 / UN R155 referenced in the documentation; an
  authorized-use warning is shown. The operator works on a vehicle or bench they
  are **authorized to test**.

---

## 6. Attack surface covered

```
1. PHYSICAL ACCESS      -> OBD-II port, CAN bus identification
2. CAN RECONNAISSANCE   -> sniff, traffic mapping, ECU identification
3. UDS DIAGNOSTICS      -> service scan, sessions, security levels
4. DTC & DATA           -> read/clear fault codes, DIDs
5. SEED-KEY             -> access to protected sessions (documented algos)
6. REPLAY & INJECTION   -> impact validation (with approval)
7. AUTOMOTIVE ETHERNET  -> DoIP (SOME/IP as an extension)
8. WIRELESS (v1.x)      -> Wi-Fi infotainment, BLE key/telematics
9. REPORTING            -> session report
```

Steps 1–6 are the backbone of Guided mode and are playable end to end on the
simulated ECU with no hardware.

---

## 7. Key decisions

| Topic | Decision |
|-------|----------|
| Language / stack | Python (`python-can`, `udsoncan`, MCP SDK, Textual, Starlette) |
| Methodology engine | Declarative YAML, closed condition grammar on `ToolResult` |
| MCP transport | HTTP localhost + Bearer token; stdio optional |
| Destructive guard | Blocking `pending-approval` queue, approved out-of-band; `--yes` ignored for non-CLI origins; stdio refuses destructive |
| Interfaces | TUI (Textual) + Web (Starlette); TUI first, Web next; same core |
| Web framework | Starlette, not FastAPI (already pulled by `mcp`; avoids a heavy dep) |
| Attack-surface map | Pure projection `build_surface(history)` in `state()`; cytoscape.js vendored |
| Real-time transport | SSE (core → browser) + POST (browser → core) |
| UDS libraries | Client: `can-isotp` + `udsoncan` (wrapped). Simulated ECU: in-house ISO-TP/UDS responder |
| Simulated ECU scope | One ECU, correct NRCs, session/security locking, one example seed-key |
| Seed-key | Pluggable framework + documented example algorithm (not OEM crypto) |
| CAN access | `python-can` as the reference CAN layer |
| Distribution | Multi-arch image; first public publish gated on an upstream-license audit |
| License | GPLv3 (copyleft, compatible with upstream GPL integration) |
| Offline | Air-gap is a supported configuration; model-agnostic enables offline via a local client |

---

## 8. Roadmap

```
v0.1  FOUNDATION   Multi-arch Dockerfile, CAN access (can0/vcan0),
                   minimal core + tool registry, CLI
v0.2  UDS          ISO-TP, UDS scan, DTC, documented seed-key,
                   + SIMULATED ECU (one ECU, correct NRCs, locking)
v0.3  MCP + AI     MCP server (tools + state), token auth,
                   destructive-action approval
v0.4  GUIDED       YAML methodology engine, steps 1-6, persistent state, TUI
v0.5  WEB + MAP    Web client (same process), attack-surface map
                   (cytoscape.js, build_surface projection), SSE+POST,
                   click-to-run Libre, Web destructive approval
v0.6  CLI / TUI    Readable result panels, no-command dashboard, next-step
                   hints; a live, visual Textual TUI (CAN/UDS activity graphs,
                   colored event log, bus/ECU device panels, action tabs)
v1.0  REPORTING    Exportable session report, docs + manual
v1.x  EXTENSIONS   Automotive Ethernet (DoIP), Wi-Fi/BLE, embedded agent
v2+   EXTENSIONS   CAN-FD, SOME/IP, firmware reverse, advanced Pi probe
```

v0.1 → v0.5 are delivered; v0.6 (CLI/TUI experience) is in progress. Guided mode in the Web client, and the session
report, are the next milestones.

---

## 9. Acceptance criteria

- **AC-01** operational in < 5 min on a clean Docker host.
- **AC-02** full CAN cycle (sniff → decode → replay → inject) without leaving CARBON.
- **AC-03** full UDS dialogue (scan → session → DTC → documented seed-key).
- **AC-04** Guided mode walks steps 1–6 with result interpretation.
- **AC-05** Libre mode shows the position and journals actions.
- **AC-06** image boots on x86 and ARM from the same source.
- **AC-07** everything works on `vcan0` with no hardware.
- **AC-08** a session report is generated at the end of a run.
- **AC-09** one session is drivable by a local model **and** a frontier model over MCP, no code change.
- **AC-10** no destructive action — even AI-requested — runs without explicit human approval.
- **AC-11** TUI and Web expose the same action set on the same core.
- **AC-12** a manual lets a new operator install and complete a CAN/UDS run on `vcan0` unaided.
- **AC-13** real hardware is usable (OBD-II/CAN USB passthrough, Wi-Fi monitor, BLE) without global `--privileged`.
