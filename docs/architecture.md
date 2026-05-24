# SD-WAN Automation Internals

This document explains how the automation works behind the scenes. It is meant
for maintainers and debuggers. The README remains the user guide for installing
and running the CLI.

## Mental Model

The tool automates a Cisco SD-WAN lab in this order:

1. Build runtime settings from YAML.
2. Configure and certificate-enable vManage.
3. Configure and certificate-enable vBond.
4. Configure and certificate-enable vSmart.
5. Configure WAN edges, generate PAYG licenses, activate them, and wait for the
   edges to join the fabric.
6. For multi-edge certificate runs, verify final BFD convergence and retry only
   the edges that did not converge.

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

1. Connect to the edge with Netmiko.
2. Optionally push initial config using `config-transaction` and `commit`.
3. If `--cert` is requested, check whether vManage already sees the edge in the
   fabric.
4. Generate one PAYG license through vManage.
5. Copy the root certificate from vBond to the edge with SCP.
6. Install the root CA chain on the edge.
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

### Orchestrator-Level BFD Retry

For multi-edge `--cert` runs, `run_edges_automation()` performs shared
convergence checks after the worker phase.

First it waits for every targeted edge to join the fabric:

```text
control_connections_up >= 2
```

If some edges do not reach that state, only those control-down edges are retried
with a fresh certificate/license flow. Edges that already have both control
connections are not retried, because they are already authenticated.

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
