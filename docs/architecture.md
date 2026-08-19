# SD-WAN Automation Internals

This document explains how the automation works behind the scenes. It is meant
for maintainers and debuggers. The README remains the user guide for installing
and running the CLI.

For a compact handoff aimed at future LLM/debugging sessions, see
`docs/llm-context.md`.

## Mental Model

The tool automates a Cisco SD-WAN lab in this order:

1. Build runtime settings from YAML.
2. Configure and certificate-enable vManage.
3. Configure and certificate-enable vBond.
4. Configure and certificate-enable vSmart.
5. Configure WAN edges, generate PAYG licenses, activate them, and wait for the
   edges to join the fabric.
6. For multi-edge certificate runs, verify control-plane fabric membership
   first, retry only edges that did not join, then verify final BFD convergence.

The main entry point is `sdwan_automation.py`. It parses CLI arguments, loads
settings through `utils/sdwan_config.py`, initializes logging, and dispatches to
component modules under `components/`.

## Configuration Loading

Runtime configuration is loaded once through `settings.load(...)` in
`utils/sdwan_config.py`.

The default variables path is:

```text
~/.config/sdwan-automation/variables.yml
```

The base template copied by `sdwan-automation init` lives at:

```text
utils/templates/sdwan_base_variables.yml
```

Important behavior:

- Existing user config files are not overwritten by bundled template changes.
- Missing timing keys still get defaults from `utils/sdwan_config.py`.
- Generated edge configs expose both management IP and system IP. Management IP
  is used for SSH/Netmiko. System IP is used for vManage health lookups.
- Edge initial config and extra-routing config are rendered from YAML into CLI
  snippets during `settings.load(...)`.

## First-Boot Orchestration

`sdwan_automation.py::_run_all()` is the full lab workflow.

The sequence is deliberately serial for controllers:

```text
Manager -> Validator -> Controller -> controller sync check -> Edges
```

The controller sync check is handled by `utils/component_sync.py`. It queries
vManage for controller status, waits, rechecks, and can reboot out-of-sync
controllers before edges start. This matters because edge onboarding can appear
successful while later BFD fails if vBond or vSmart is rebooting or out of sync.

Edges are handled as a parallel worker phase, but some edge certificate steps are
serialized internally. See the edge section below.

In the surrounding Ansible workflow, Day 1 starts `sdwan-automation deploy`.
That command still uses the tool's built-in retry budget. If one edge remains
outside the fabric after those retries, Day 1 is allowed to continue as long as
the async deploy process actually completed. Day 2 then runs the targeted repair
command:

```bash
sdwan-automation edges failed --cert
```

This gives vManage and the lab more time to settle before trying only the edges
that are still missing full control-plane membership.

## Manager Certificate Flow

Implemented in `components/sdwan_manager.py`.

When `cert=True`, vManage does the following:

1. Generate an RSA key in vShell with OpenSSL.
2. Generate an enterprise root certificate.
3. Read the root certificate from vShell.
4. Configure vManage through the `/dataservice/settings/configuration/...` APIs:
   organization, vBond IP, enterprise certificate mode, enterprise root CA, and
   CSR properties.
5. Request vManage CSR generation through the API.
6. Poll vShell until the CSR file exists.
7. Sign the CSR with the local enterprise root.
8. Install the signed certificate back into vManage with the certificate install
   API.

The CSR generation step is retried because vManage may not be immediately ready
after first boot.

## Validator And Controller Certificate Flow

Implemented in:

```text
components/sdwan_validator.py
components/sdwan_controller.py
utils/sdwan_cert.py
```

vBond and vSmart use the same pattern:

1. Connect to vManage and read the enterprise root key and certificate.
2. Write that material to the target device through vShell.
3. Add the device to vManage with `generateCSR=True`.
4. Wait for CSR generation.
5. Sign the device CSR locally on that device using the copied root material.
6. Install the signed certificate into vManage through
   `/dataservice/certificate/install/signedCert`.

The target device's certificate is not pushed manually to the device. vManage is
the source of truth for controller certificate installation after the signed cert
is uploaded.

## Edge Certificate And License Flow

Implemented in `components/sdwan_edges.py`.

Each edge worker performs:

1. Connect to the edge with Netmiko using the `cisco_viptela` driver
   (`shared.edge_device_type`) — cEdges run the Viptela config model
   (`config-transaction`) in controller mode, not classic IOS.
2. Optionally push initial config using `config-transaction` and `commit`,
   first waiting via a readiness gate (`wait_for_config_ready`) until confd
   accepts `config-transaction` (a freshly-booted vEdge answers SSH before confd
   is ready).
3. If `--cert` is requested, check whether vManage already sees the edge in the
   fabric.
4. Generate one PAYG license through vManage.
5. Copy the root certificate from vBond to the edge with SCP (once per edge per
   run — skipped on chassis regenerations, since the root chain persists).
6. Install the root CA chain on the edge (also once per edge per run).
7. Activate the PAYG license on the edge with:

```text
request platform software sdwan vedge_cloud activate chassis-number <id> token <token>
```

8. Wait for vManage to report that the edge has joined the fabric.

The per-edge fabric success signal is:

```text
control_connections_up >= 2
```

That means the edge has control connections to both vBond and vSmart. vBond alone
is not enough because an edge can reach vBond before the signed device
certificate is fully installed.

## Why Edge Activation Is Serialized

The edge workers are parallel, but the `vedge_cloud activate` command is guarded
by `_ACTIVATION_LOCK`.

Only one edge activates at a time, then the worker holds the lock for
`edge_activation_gap_seconds`. This gives vManage time to process one CSR before
the next edge submits another.

This was added because concurrent PAYG-generated chassis activation can produce
race-like failures such as:

```text
SYSTEM_LICENSE_MISMATCH: BYOL instance is being associated to PAYG license
vedgeCertificateState: certinstallfailed
```

Initial config, root certificate copy, root certificate install, and fabric
waiting still run in parallel. Only activation is serialized.

## Edge Retry Logic

There are two retry layers.

### Per-Edge Certificate Retry

For single-edge runs, after activation the worker polls vManage health until the
edge has at least two control connections.

For multi-edge runs, the worker stops after successful PAYG activation. Final
success is handled by shared convergence gates. This avoids each edge spending
its own long timeout on transient vManage certificate states while the fabric as
a whole is still converging.

If that times out, the worker queries:

```text
/dataservice/system/device/vedges
```

and inspects `vedgeCertificateState` for the generated chassis ID.

If vManage reports one of these states:

```text
certinstalled
certinstallfailed
```

the code reconnects to the edge if the SSH session went stale, sends:

```text
clear sdwan control connections
```

and retries the fabric wait.

If vManage reports a state such as `CSR Generated` or no state at all, the worker
does not clear control connections. In that state vManage has not completed the
signing or delivery phase, so clearing is more likely to disrupt than fix the
flow.

### Orchestrator-Level Fabric Retry

For multi-edge `--cert` runs, `run_edges_automation()` performs shared
convergence checks after the worker phase.

First it waits for every targeted edge to join the fabric:

```text
control_connections_up >= 2
```

If some edges do not reach that state, only those control-down edges are retried
with a fresh certificate/license flow. Edges that already have both control
connections are not retried, because they are already authenticated.

During this shared fabric gate, the code also watches the latest generated
chassis ID for each down edge:

- **no chassis ID at all** → the edge failed before activation (initial config,
  SSH, or root cert issues). Immediately mark for regeneration instead of waiting
  the full fabric timeout. This fast-bail saves ~10 minutes per pre-activation
  failure.
- `certinstallfailed` → stop waiting and regenerate a fresh chassis immediately,
  instead of burning the full fabric timeout.
- `certinstalled` but control still `< 2` → **never regenerate.** The cert works,
  so a slow control plane is a convergence/data-plane matter. The edge gets a
  fresh convergence window (a per-edge deadline, reset the moment its cert
  installs); if it still cannot reach `2`, the gate raises it as a
  data-plane/TLOC issue rather than churning. Regenerating a working
  `certinstalled` identity was a real bug — it tore the edge down repeatedly and
  kept it cycling for ~45 minutes.
- never installed by the timeout → regenerate (its CSR never completed).

The retry budget is tracked per edge, not per command. This matters when several
edges fail at different times: one edge can be retried without consuming the
entire budget for another edge that has not yet had the same number of repair
attempts.

Only after all targeted edges have joined the fabric does it check BFD:

```text
bfd_sessions_up > 0
```

If all edges have control connections but BFD stays down, the automation treats
that as a data-plane/TLOC problem rather than a certificate install problem. It
does not keep generating new PAYG chassis for edges that are already
authenticated.

This exists because BFD is a final fabric-level condition. It should not be used
as the per-edge certificate success signal during the first worker phase: the
first edge to join a fresh lab may have no BFD peers yet.

### Targeted Repair Runs

The CLI supports a repair target:

```bash
sdwan-automation edges failed --cert
```

`failed` selects configured edges whose vManage health entry has fewer than two
control connections. This is intentionally not based on BFD. If an edge has
`2/2` control connections but BFD is down, the certificate has already done its
job and the problem is likely data-plane, TLOC, or routing.

This target is useful in orchestrators such as Ansible. Day 1 can run full
first-boot with the built-in retry budget, tolerate an edge that is still not in
fabric, and Day 2 can run `edges failed --cert` after the lab has had more time
to settle.

## Logging

Logging is initialized in `utils/logging.py`.

Default log directory:

```text
~/.config/sdwan-automation/logs/
```

Each run logs a grep-friendly marker:

```text
========== RUN START: sdwan-automation <args> ==========
```

Most component flows also log structured details such as selected component,
targets, flags, config file, and per-edge labels. Parallel edge output uses
thread-local labels such as `[edge1]` so interleaved worker logs can still be
read.

Useful log patterns:

- `RUN START` identifies command boundaries.
- `Run Summary` appears for automation commands and records total runtime,
  slowest phases, and retry counters. It is intentionally suppressed for
  read-only `show` and `sdk` commands.
- `Edge has joined the SD-WAN fabric` means vManage reports at least two control
  connections for that edge.
- `BFD did not converge before timeout` means certificate install may have
  worked but final data-plane fabric convergence did not.
- `vManage chassis cert state` shows the per-chassis certificate state used to
  decide whether a clear/retry is safe.

## Status APIs Used As Truth Sources

The automation deliberately prefers vManage APIs for final state checks:

- Controller status:
  `/dataservice/system/device/controllers`
- WAN edge health:
  `/dataservice/health/devices?page_size=12000&personality=vedge`
- WAN edge certificate inventory:
  `/dataservice/system/device/vedges`

Edge CLI is still used for local actions such as installing the root chain,
activating PAYG, clearing control connections, and pushing config. It is not used
as the main device-certificate success signal because commands such as
`show sdwan certificate validity` can collide with vManage-driven NETCONF and
certificate processes.

## Important Failure Modes

### Orphaned Chassis Entries

Failed PAYG attempts can leave stale chassis rows in vManage. These show up in:

```text
sdwan-automation show licenses
```

They are useful for debugging because they show historical failed chassis IDs and
their `vedgeCertificateState`. They can also make the inventory noisy.

### Stale SSH Sessions

Long vManage waits can leave Netmiko sessions closed. `ensure_connection()` now
checks connection liveness and reconnects before reuse. This is especially
important before retrying `clear sdwan control connections`.

### Control Connections Without BFD

An edge with `2/2` control connections but `0/0` or `0/N` BFD is authenticated
but not fully useful for the lab. That is why the final multi-edge gate checks
BFD after all workers finish.

## Where To Change Behavior

- CLI dispatch and full first-boot order: `sdwan_automation.py`
- Settings and defaults: `utils/sdwan_config.py`
- User template defaults: `utils/templates/sdwan_base_variables.yml`
- Manager certificate flow: `components/sdwan_manager.py`
- vBond certificate flow: `components/sdwan_validator.py`
- vSmart certificate flow: `components/sdwan_controller.py`
- Edge onboarding, PAYG activation, and BFD retry: `components/sdwan_edges.py`
- vManage status tables and health parsing: `utils/manager_api_status.py`
- Netmiko connection and config helpers: `utils/netmiko.py`
- Shared certificate helper functions: `utils/sdwan_cert.py`
