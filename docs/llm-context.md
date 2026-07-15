# LLM Context: SD-WAN Automation

Use this as the short context file for future LLM sessions. The longer
maintainer guide is `docs/architecture.md`; this file captures the high-signal
workflow rules and current design decisions.

## Goal

This repo automates Cisco SD-WAN lab bring-up for netlab/containerlab:

```text
Manager -> Validator -> Controller -> controller sync check -> Edges
```

The hard part is WAN edge certificate onboarding. The desired final state is:

```text
all controllers: In Sync / certificate Installed
all edges: control_connections_up >= 2
all edges: bfd_sessions_up > 0 after every edge has joined control
```

## Main Commands

```bash
sdwan-automation deploy --host-vars /path/to/host_vars
sdwan-automation first-boot
sdwan-automation edges all --cert
sdwan-automation edges failed --cert
sdwan-automation show devices
sdwan-automation show licenses
```

`deploy` generates variables and then runs full first-boot. `first-boot` uses
the existing user variables file. `show` commands are read-only and intentionally
do not print run summaries.

## Configuration Paths

Runtime config defaults to:

```text
~/.config/sdwan-automation/variables.yml
~/.config/sdwan-automation/base.yml
~/.config/sdwan-automation/logs/
```

The bundled template is:

```text
utils/templates/sdwan_base_variables.yml
```

Existing user config files are not overwritten when bundled defaults change.
Missing keys still fall back to defaults in `utils/sdwan_config.py`.

## Edge Onboarding Rules

The edge cert workflow lives in `components/sdwan_edges.py`.

Core rules:

- Do not use edge CLI certificate validity as the main success signal.
- Use vManage health: `control_connections_up >= 2`.
- `1/1` control usually means vBond-only bootstrap, not full fabric membership.
- BFD is checked only after all targeted edges have full control connections.
- If all edges have `2/2` control but BFD is down, treat it as data-plane/TLOC,
  not cert onboarding.
- Edges connect with the `cisco_viptela` Netmiko driver (`shared.edge_device_type`),
  like the controllers — cEdges run the Viptela config model (`config-transaction`)
  in controller mode, not classic IOS.
- Before pushing initial edge config, a readiness gate (`wait_for_config_ready`)
  probes `config-transaction` until confd accepts it — a freshly-booted vEdge
  answers SSH before confd is ready.
- Never regenerate a chassis whose latest cert state is `certinstalled`. If
  control is still `<2` with a good cert, that is convergence/data-plane, not a
  cert failure; regenerating a working identity only churns (was a real bug that
  kept edges cycling for ~45 min).

PAYG activation is serialized with `_ACTIVATION_LOCK`; initial config, root cert
copy/install, and waits can still run in parallel. The root CA chain is installed
once per edge per run — chassis regenerations skip the SCP + install because the
root chain persists across chassis.

## Retry Model

There are two important retry layers.

Single-edge cert runs:

- Activate PAYG.
- Wait for vManage to report `control_connections_up >= 2`.
- On timeout, inspect `vedgeCertificateState`.
- `certinstalled` or `certinstallfailed` can justify `clear sdwan control connections`.
- `tokengenerated`, `csrgenerated`, `CSR Generated`, or missing state means
  vManage has not completed signing/pushing; clearing is not useful.

Multi-edge cert runs:

- Workers stop after successful PAYG activation.
- Shared fabric gate waits for all targeted edges to reach `control_connections_up >= 2`.
- Gate watches each latest chassis state:
  - `certinstallfailed` -> regenerate a fresh chassis immediately (fast-bail).
  - `certinstalled` but control still `<2` -> NEVER regenerate; give it a fresh
    convergence window (per-edge deadline, reset when the cert installs). If it
    still can't reach `2`, raise it as a data-plane/TLOC issue — do not churn.
  - never-installed by the timeout -> regenerate (its CSR never completed).
- Retry target is only cert-failed / uninstalled edges (never `certinstalled` ones).
- Retry budget is tracked per edge, not per command round.
- BFD gate runs only after all targeted edges are in control fabric.

## Repair Command

Use this for post-failure remediation:

```bash
sdwan-automation edges failed --cert
```

`failed` means configured edges with fewer than two vManage control connections.
It intentionally does not select based on BFD.

In the surrounding Ansible workflow:

- Day 1 runs `sdwan-automation deploy`.
- Day 1 may continue if edge onboarding failed but the async deploy completed.
- Day 2 runs `sdwan-automation edges failed --cert`.

## Logs And Debugging

Run boundaries:

```text
========== RUN START: sdwan-automation <args> ==========
```

Useful commands:

```bash
sdwan-automation show devices
sdwan-automation show licenses
```

`show devices` gives controller state and WAN edge control/BFD state.
`show licenses` shows vManage WAN Edge certificate inventory and orphaned failed
PAYG chassis rows.

Important log signals:

- `vManage chassis cert state: 'certinstallfailed'`: vManage failed delivery for
  that generated chassis; retrying with a fresh chassis may help.
- `Edge has joined the SD-WAN fabric`: vManage sees at least two control
  connections for that edge.
- `BFD did not converge before timeout`: cert may be fine; look at data plane.
- `SYSTEM_LICENSE_MISMATCH: BYOL instance is being associated to PAYG license`:
  environment/licensing mismatch observed during failed edge onboarding.

## Common Mistakes

- Do not retry certs for an edge that already has `2/2` control just because BFD
  is zero.
- Do not use BFD as the per-edge cert success signal in a fresh lab.
- Do not treat `certinstalled` from vManage as definitive proof that the edge
  has the cert; `2/2` control is the better programmatic proof.
- Do not clear control connections while vManage is still at token/CSR states.
- Do not assume bundled template changes updated existing user config files.

## Key Files

- `sdwan_automation.py`: CLI dispatch, deploy/first-boot orchestration.
- `components/sdwan_edges.py`: edge PAYG/cert/fabric retry logic.
- `utils/manager_api_status.py`: vManage status APIs and show tables.
- `utils/sdwan_config.py`: YAML loading, defaults, rendered edge config.
- `utils/netmiko.py`: SSH connection, stale-session handling, config push.
- `utils/run_stats.py`: run summary timing/counters for automation commands.
- `docs/architecture.md`: detailed maintainer guide.
- `docs/topology-generation.md`: netlab-to-variables generation details.
