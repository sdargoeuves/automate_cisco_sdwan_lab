#!/usr/bin/env python3
"""Join per-chassis cert-install outcomes to their activation-time snapshots.

Reads the sdwan-automation log and, for every PAYG chassis, correlates:
  * the ``Chassis snapshot (pre-activate)`` / ``(post-activate-gap)`` lines
    emitted by ``_log_chassis_authorization_snapshot`` (was the serial present
    and valid in vManage when we activated?), and
  * the chassis's ``vedgeCertificateState`` timeline and final outcome
    (``certinstalled`` / joined vs ``certinstallfailed``), including how long it
    sat in ``csrgenerated`` before the terminal state.

Purpose: test whether ``certinstallfailed`` correlates with the chassis serial
not having propagated to the controllers (vBond ``SERNTPRES``) by activation
time. No dependencies beyond the stdlib.

Usage:
    python tools/analyze_cert_runs.py [LOGFILE] [--since 'YYYY-MM-DD HH:MM'] [--all]

By default it analyses from the last ``deploy`` RUN START to the end of the
file; ``--all`` scans the whole file, ``--since`` overrides the start.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

DEFAULT_LOG = Path.home() / ".config/sdwan-automation/logs/sdwan_automation.log"

TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+"
LINE_RE = re.compile(rf"^{TS} \w+ [\w.]+: (.*)$")

CHASSIS = r"(C8K-PAYG-[0-9a-f]{3}(?:-[0-9a-f]+)+)"
RE_SNAP_PRESENT = re.compile(
    rf"Chassis snapshot \((pre-activate|post-activate-gap)\) for {CHASSIS}: (\{{.*\}})$"
)
RE_SNAP_ABSENT = re.compile(
    rf"Chassis snapshot \((pre-activate|post-activate-gap)\): {CHASSIS} NOT PRESENT"
)
RE_ACTIVATE = re.compile(rf"Activating PAYG license for chassis {CHASSIS} \(attempt")
RE_STATE_MULTI = re.compile(rf"vManage cert state for latest chassis {CHASSIS}: '(\w+)'")
RE_STATE_SINGLE = re.compile(r"vManage chassis cert state: '(\w+)'")
# Control-conn trace. Two log-format eras (both may appear in one log):
#   OLD: "[edge] control connections up: N"  /  "edge: control connections up: N"
#   NEW: "[edge] [+Ns] control conns up: N, bfd up: M, reachability: R"
#        "edge: [+Ns] control conns up: N, bfd up: M, reachability: R"
# `conn(?:ection)?s` matches both "conns" and "connections". Value is an int or
# "None" (edge absent from health).
RE_CONNS = re.compile(r"control conn(?:ection)?s up: (\d+|None)")
RE_CONNS_LEADING = re.compile(
    r"^([\w-]+): (?:\[\+\d+s\] )?control conn(?:ection)?s up:"
)
RE_JOINED = re.compile(r"Edge has joined the SD-WAN fabric\.")
RE_EDGE_BRACKET = re.compile(r"^\[([\w-]+)\] ")
RE_EDGE_LEADING = re.compile(r"^([\w-]+) vManage cert state")
RE_SERNTPRES = re.compile(r"SERNTPRES.*?(\d{4}-\d{2}-\d{2}T[\d:+]+)")

SUCCESS_STATES = {"certinstalled"}
FAIL_STATES = {"certinstallfailed"}


class Chassis:
    __slots__ = (
        "cid", "edge", "activate_ts", "pre", "post", "states", "joined_ts", "conns"
    )

    def __init__(self, cid: str):
        self.cid = cid
        self.edge: str | None = None
        self.activate_ts: str | None = None
        self.pre: dict | None = None
        self.post: dict | None = None
        self.states: list[tuple[str, str]] = []  # (ts, state)
        self.joined_ts: str | None = None
        self.conns: list[tuple[str, int | None]] = []  # (ts, control_conns_up)

    def add_conns(self, ts: str, n: int | None) -> None:
        if not self.conns or self.conns[-1][1] != n:
            self.conns.append((ts, n))

    def conns_trace(self) -> str:
        if not self.conns:
            return "—"
        return "→".join("x" if n is None else str(n) for _, n in self.conns)

    def flapped(self) -> bool:
        """True if control_connections_up ever dropped after rising — a flap."""
        seq = [n for _, n in self.conns if n is not None]
        return any(b < a for a, b in zip(seq, seq[1:]))

    def short(self) -> str:
        return self.cid.split("-")[2] if self.cid.startswith("C8K-PAYG-") else self.cid

    def add_state(self, ts: str, state: str) -> None:
        if not self.states or self.states[-1][1] != state:
            self.states.append((ts, state))

    def csr_ts(self) -> str | None:
        return next((ts for ts, s in self.states if s == "csrgenerated"), None)

    def terminal(self) -> tuple[str | None, str | None]:
        """Return (ts, state) of the outcome: certinstalled/failed or joined."""
        for ts, s in reversed(self.states):
            if s in SUCCESS_STATES or s in FAIL_STATES:
                return ts, s
        if self.joined_ts:
            return self.joined_ts, "certinstalled"
        return None, None

    def outcome(self) -> str:
        _, s = self.terminal()
        if s in SUCCESS_STATES:
            return "SUCCESS"
        if s in FAIL_STATES:
            return "FAIL"
        return "?"


def _secs(a: str, b: str) -> int:
    """Whole seconds between two 'YYYY-MM-DD HH:MM:SS' strings (b - a)."""
    def to_s(t: str) -> int:
        d, hms = t.split(" ")
        y, mo, dy = map(int, d.split("-"))
        h, mi, s = map(int, hms.split(":"))
        return ((((y * 12 + mo) * 31 + dy) * 24 + h) * 60 + mi) * 60 + s
    return to_s(b) - to_s(a)


def _fmt_dur(secs: int | None) -> str:
    if secs is None:
        return "—"
    return f"{secs // 60}m{secs % 60:02d}s"


def _edge_of(msg: str) -> str | None:
    m = RE_EDGE_BRACKET.match(msg)
    if m:
        return m.group(1)
    m = RE_EDGE_LEADING.match(msg)
    return m.group(1) if m else None


def parse(lines: list[str]):
    chassis: dict[str, Chassis] = {}
    edge_current: dict[str, str] = {}  # edge -> current chassis id
    serntpres: list[str] = []

    def get(cid: str) -> Chassis:
        return chassis.setdefault(cid, Chassis(cid))

    for raw in lines:
        # Real vBond teardown rows carry a DOWNTIME timestamp; the "- Serial
        # Number not present." legend line does not, so it is filtered out.
        if "SERNTPRES" in raw and " - " not in raw:
            sm = RE_SERNTPRES.search(raw)
            if sm and sm.group(1) not in serntpres:
                serntpres.append(sm.group(1))
        m = LINE_RE.match(raw)
        if not m:
            continue
        ts, msg = m.group(1), m.group(2)
        edge = _edge_of(msg)

        sm = RE_ACTIVATE.search(msg)
        if sm:
            c = get(sm.group(1))
            c.edge = c.edge or edge
            c.activate_ts = c.activate_ts or ts
            if edge:
                edge_current[edge] = sm.group(1)
            continue

        sm = RE_SNAP_PRESENT.search(msg)
        if sm:
            when, cid, blob = sm.group(1), sm.group(2), sm.group(3)
            c = get(cid)
            c.edge = c.edge or edge
            try:
                data = ast.literal_eval(blob)
            except (ValueError, SyntaxError):
                data = {"_raw": blob}
            data["_present"] = True
            setattr(c, "pre" if when == "pre-activate" else "post", data)
            continue

        sm = RE_SNAP_ABSENT.search(msg)
        if sm:
            when, cid = sm.group(1), sm.group(2)
            c = get(cid)
            c.edge = c.edge or edge
            setattr(c, "pre" if when == "pre-activate" else "post", {"_present": False})
            continue

        sm = RE_STATE_MULTI.search(msg)
        if sm:
            c = get(sm.group(1))
            c.edge = c.edge or edge
            c.add_state(ts, sm.group(2))
            continue

        sm = RE_STATE_SINGLE.search(msg)
        if sm and edge and edge in edge_current:
            get(edge_current[edge]).add_state(ts, sm.group(1))
            continue

        sm = RE_CONNS.search(msg)
        if sm:
            # Gate lines are "edge: control connections up: N" (no bracket);
            # single-edge lines carry the [edge] thread label.
            lead = RE_CONNS_LEADING.match(msg)
            who = lead.group(1) if lead else edge
            if who and who in edge_current:
                n = None if sm.group(1) == "None" else int(sm.group(1))
                get(edge_current[who]).add_conns(ts, n)
            continue

        if RE_JOINED.search(msg) and edge and edge in edge_current:
            get(edge_current[edge]).joined_ts = ts

    return chassis, serntpres


def _pre_cell(snap: dict | None, key: str) -> str:
    if snap is None:
        return "—"
    if not snap.get("_present", False):
        return "ABSENT" if key == "present" else "—"
    if key == "present":
        return "yes"
    return str(snap.get(key, "—"))


def report(chassis: dict[str, Chassis], serntpres: list[str]) -> None:
    rows = [c for c in chassis.values() if c.activate_ts or c.states]
    rows.sort(key=lambda c: (c.activate_ts or c.states[0][0] if c.states else ""))

    header = (
        f"{'CHASSIS':<8} {'EDGE':<9} {'PRE:valid':<10} {'OUTCOME':<8} "
        f"{'csr→end':<8} {'FLAP':<5} {'CONNS(trace)':<18}"
    )
    print(header)
    print("-" * len(header))
    for c in rows:
        csr = c.csr_ts()
        tts, _ = c.terminal()
        dur = _secs(csr, tts) if csr and tts else None
        flap = "YES" if c.flapped() else ("no" if c.conns else "—")
        print(
            f"{c.short():<8} {(c.edge or '?'):<9} "
            f"{_pre_cell(c.pre, 'validity'):<10} "
            f"{c.outcome():<8} {_fmt_dur(dur):<8} {flap:<5} {c.conns_trace():<18}"
        )

    succ = [c for c in rows if c.outcome() == "SUCCESS"]
    fail = [c for c in rows if c.outcome() == "FAIL"]
    print()
    print(f"Totals: {len(succ)} success, {len(fail)} fail, "
          f"{len(rows) - len(succ) - len(fail)} in-progress/unknown")

    def bucket(group: list[Chassis], label: str) -> None:
        if not group:
            return
        present = sum(1 for c in group if c.pre and c.pre.get("_present"))
        absent = sum(1 for c in group if c.pre and not c.pre.get("_present"))
        nosnap = sum(1 for c in group if c.pre is None)
        valids = {}
        for c in group:
            if c.pre and c.pre.get("_present"):
                v = str(c.pre.get("validity", "?"))
                valids[v] = valids.get(v, 0) + 1
        durs = [
            _secs(c.csr_ts(), c.terminal()[0])
            for c in group
            if c.csr_ts() and c.terminal()[0]
        ]
        avg = f"{sum(durs) // len(durs)}s" if durs else "—"
        traced = [c for c in group if c.conns]
        flapped = sum(1 for c in traced if c.flapped())
        flap_str = f"{flapped}/{len(traced)}" if traced else "no trace"
        print(
            f"  {label:<8} present@activate={present} absent={absent} "
            f"no-snapshot={nosnap} | validity={valids or '—'} | avg csr→end={avg} "
            f"| control-conn flaps={flap_str}"
        )

    print("Correlation (pre-activate snapshot + control-plane vs outcome):")
    bucket(succ, "SUCCESS")
    bucket(fail, "FAIL")

    if serntpres:
        print()
        print(f"vBond SERNTPRES teardowns seen in diagnostics ({len(serntpres)}):")
        for t in serntpres:
            print(f"  {t}")

    print()
    print("Read: pre-activate validity is expected to be identical (propagation "
          "was ruled out). The live signal is FLAP — if FAIL rows flap "
          "(control conns rise then drop, e.g. 0→1→0) during csr→install while "
          "SUCCESS rows hold steady to 2+, the driver is control-plane "
          "instability during the vManage cert push (consistent with the "
          "BYOL→PAYG mismatch churning DTLS).")


def _slice(lines: list[str], since: str | None, scan_all: bool) -> list[str]:
    if scan_all:
        return lines
    if since:
        return [ln for ln in lines if LINE_RE.match(ln) and ln[:19] >= since]
    # default: from the last `deploy` RUN START
    start = 0
    for i, ln in enumerate(lines):
        if "RUN START" in ln and "deploy" in ln:
            start = i
    return lines[start:]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logfile", nargs="?", default=str(DEFAULT_LOG))
    ap.add_argument("--since", help="Only lines at/after 'YYYY-MM-DD HH:MM(:SS)'")
    ap.add_argument("--all", action="store_true", help="Scan the entire file")
    args = ap.parse_args()

    path = Path(args.logfile)
    if not path.exists():
        raise SystemExit(f"Log not found: {path}")
    lines = path.read_text(errors="replace").splitlines()
    window = _slice(lines, args.since, args.all)
    chassis, serntpres = parse(window)
    if not chassis:
        print("No chassis activity found in the selected window.")
        return
    report(chassis, serntpres)


if __name__ == "__main__":
    main()
