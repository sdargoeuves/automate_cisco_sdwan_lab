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
# BFD sessions up — only present in the NEW log format (same line as conns).
RE_BFD = re.compile(r"bfd up: (\d+|None)")

# Abbreviations for the vManage cert-state path column.
STATE_ABBR = {
    "tokengenerated": "tok",
    "csrgenerated": "csr",
    "certinstalled": "installed",
    "certinstallfailed": "FAILED",
}
RE_JOINED = re.compile(r"Edge has joined the SD-WAN fabric\.")
RE_EDGE_BRACKET = re.compile(r"^\[([\w-]+)\] ")
RE_EDGE_LEADING = re.compile(r"^([\w-]+) vManage cert state")
RE_SERNTPRES = re.compile(r"SERNTPRES.*?(\d{4}-\d{2}-\d{2}T[\d:+]+)")

SUCCESS_STATES = {"certinstalled"}
FAIL_STATES = {"certinstallfailed"}


class Chassis:
    __slots__ = (
        "cid", "edge", "activate_ts", "pre", "post", "states", "joined_ts",
        "conns", "bfds", "license_mismatch",
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
        self.bfds: list[tuple[str, int | None]] = []  # (ts, bfd_sessions_up)
        # True if this chassis's on-failure diagnostic dump contained
        # %VDAEMON-6-SYSTEM_LICENSE_MISMATCH (BYOL↔PAYG association mismatch).
        self.license_mismatch: bool = False

    def add_conns(self, ts: str, n: int | None) -> None:
        if not self.conns or self.conns[-1][1] != n:
            self.conns.append((ts, n))

    def add_bfd(self, ts: str, n: int | None) -> None:
        if not self.bfds or self.bfds[-1][1] != n:
            self.bfds.append((ts, n))

    @staticmethod
    def _trace(series: list[tuple[str, int | None]]) -> str:
        if not series:
            return "—"
        return "→".join("x" if n is None else str(n) for _, n in series)

    def conns_trace(self) -> str:
        return self._trace(self.conns)

    def bfd_trace(self) -> str:
        return self._trace(self.bfds)

    def state_path(self) -> str:
        """Abbreviated vManage cert-state sequence, e.g. 'tok→csr→installed'."""
        if not self.states:
            return "—"
        return "→".join(STATE_ABBR.get(s, s) for _, s in self.states)

    def pipeline_window(self) -> tuple[str | None, str | None]:
        """(start, end) while this chassis was in the vManage signing pipeline.

        Start = activation (or CSR if activation wasn't captured); end = terminal
        state. Used to test whether failures correlate with other chassis being
        signed concurrently (the BYOL↔PAYG race hypothesis).
        """
        start = self.activate_ts or self.csr_ts()
        end = self.terminal()[0]
        if end is None and self.states:
            end = self.states[-1][0]
        return start, end

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

    def fabric_ts(self) -> str | None:
        """Timestamp control connections first reached >=2 (fabric membership).

        The multi-edge gate has no per-edge "joined" log line, so reaching 2
        control connections in the trace is our join signal there.
        """
        for ts, n in self.conns:
            if (n or 0) >= 2:
                return ts
        return self.joined_ts

    def reached_fabric(self) -> bool:
        return self.fabric_ts() is not None

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
        # Multi-edge gate: an edge can reach 2 control conns (joined) without us
        # capturing its certinstalled line — treat that as success too.
        if self.reached_fabric():
            return "SUCCESS"
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
    # Chassis whose on-failure `show logging` diagnostic dump we're currently
    # reading (its raw device-output lines don't match LINE_RE).
    diag_chassis: str | None = None

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
            # Raw device output (e.g. inside a diagnostic dump). Attribute a
            # BYOL↔PAYG mismatch to the chassis whose `show logging` we're in.
            if diag_chassis and "SYSTEM_LICENSE_MISMATCH" in raw:
                get(diag_chassis).license_mismatch = True
            continue
        ts, msg = m.group(1), m.group(2)
        edge = _edge_of(msg)
        # Enter/exit "reading a show-logging diagnostic dump" mode. Any real log
        # line ends a prior dump; the show-logging header starts a new one.
        if "Edge cert diagnostic: show logging" in msg and edge in edge_current:
            diag_chassis = edge_current[edge]
        else:
            diag_chassis = None

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
                c = get(edge_current[who])
                c.add_conns(ts, n)
                bm = RE_BFD.search(msg)  # new-format lines only
                if bm:
                    c.add_bfd(ts, None if bm.group(1) == "None" else int(bm.group(1)))
            continue

        if RE_JOINED.search(msg) and edge and edge in edge_current:
            get(edge_current[edge]).joined_ts = ts

    return chassis, serntpres


def report(chassis: dict[str, Chassis], serntpres: list[str]) -> None:
    rows = [c for c in chassis.values() if c.activate_ts or c.states]
    rows.sort(key=lambda c: (c.activate_ts or c.states[0][0] if c.states else ""))

    header = (
        f"{'CHASSIS':<8} {'EDGE':<9} {'OUTCOME':<8} {'PATH':<22} "
        f"{'csr→end':<8} {'FLAP':<5} {'CONNS':<13} {'BFD':<8}"
    )
    print(header)
    print("-" * len(header))
    for c in rows:
        csr = c.csr_ts()
        tts, _ = c.terminal()
        dur = _secs(csr, tts) if csr and tts else None
        flap = "YES" if c.flapped() else ("no" if c.conns else "—")
        print(
            f"{c.short():<8} {(c.edge or '?'):<9} {c.outcome():<8} "
            f"{c.state_path():<22} {_fmt_dur(dur):<8} {flap:<5} "
            f"{c.conns_trace():<13} {c.bfd_trace():<8}"
        )

    succ = [c for c in rows if c.outcome() == "SUCCESS"]
    fail = [c for c in rows if c.outcome() == "FAIL"]
    print()
    print(f"Totals: {len(succ)} success, {len(fail)} fail, "
          f"{len(rows) - len(succ) - len(fail)} in-progress/unknown")

    # Per-edge onboarding: how many chassis each edge burned before joining, and
    # the wall-clock from its first activation to fabric join. The chassis count
    # (draws) is what actually drives onboarding time.
    edges = sorted({c.edge for c in rows if c.edge})
    if edges:
        print()
        print("Per-edge onboarding (chassis drawn until join — the cost metric):")
        for e in edges:
            ec = [c for c in rows if c.edge == e]
            ec.sort(key=lambda c: c.activate_ts or "")
            nf = sum(1 for c in ec if c.outcome() == "FAIL")
            ns = sum(1 for c in ec if c.outcome() == "SUCCESS")
            first_act = next((c.activate_ts for c in ec if c.activate_ts), None)
            win = next((c for c in ec if c.outcome() == "SUCCESS"), None)
            join_ts = None
            if win:
                join_ts = win.fabric_ts() or win.joined_ts or win.terminal()[0]
            span = _fmt_dur(_secs(first_act, join_ts)) if first_act and join_ts else "—"
            joined = "joined" if win else "NOT joined"
            print(
                f"  {e:<9} {len(ec)} chassis ({nf} fail → {ns} success)  "
                f"{joined}  activate→join {span}"
            )

    decided = len(succ) + len(fail)
    if decided:
        pct = round(100 * len(fail) / decided)
        print()
        print(
            f"certinstallfailed draw rate: {len(fail)}/{decided} decided chassis "
            f"({pct}%) — THIS is the onboarding-time lever (fast-bail already "
            "regenerates promptly; fewer bad draws = faster lab)."
        )

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

    # Concurrency test: was each chassis alone in vManage's signing pipeline, or
    # were other chassis being signed at the same time? If FAIL chassis overlap
    # more peers than SUCCESS chassis, the BYOL↔PAYG concurrency race is real and
    # full serialization should help. If failures happen at 0 overlap too,
    # concurrency is NOT the driver.
    def overlaps(c: Chassis) -> int | None:
        a0, a1 = c.pipeline_window()
        if not (a0 and a1):
            return None
        n = 0
        for o in rows:
            if o is c:
                continue
            b0, b1 = o.pipeline_window()
            if b0 and b1 and a0 <= b1 and b0 <= a1:  # windows intersect
                n += 1
        return n

    def conc_summary(group: list[Chassis], label: str) -> None:
        vals = [ov for c in group if (ov := overlaps(c)) is not None]
        if not vals:
            print(f"  {label:<8} peers-in-pipeline: no timing")
            return
        alone = sum(1 for v in vals if v == 0)
        print(
            f"  {label:<8} peers-in-pipeline avg={sum(vals)/len(vals):.1f} "
            f"max={max(vals)} | signed ALONE (0 peers): {alone}/{len(vals)}"
        )

    print()
    print("Concurrency test (peers being signed during each chassis's window):")
    conc_summary(succ, "SUCCESS")
    conc_summary(fail, "FAIL")

    # The decision metric: does being alone in the pipeline lower the fail rate?
    # If solo ≈ crowded, serialization won't help. If solo << crowded, it will.
    solo_f = solo_t = crowd_f = crowd_t = 0
    for c in succ + fail:
        ov = overlaps(c)
        if ov is None:
            continue
        is_fail = c.outcome() == "FAIL"
        if ov == 0:
            solo_t += 1
            solo_f += is_fail
        else:
            crowd_t += 1
            crowd_f += is_fail
    if solo_t and crowd_t:
        print(
            f"  fail rate:  ALONE {solo_f}/{solo_t} ({100*solo_f//solo_t}%)  "
            f"vs  CROWDED {crowd_f}/{crowd_t} ({100*crowd_f//crowd_t}%)  "
            "→ serialization helps only by this gap; the ALONE rate is the floor."
        )
    lone_fail = [
        c for c in fail if (ov := overlaps(c)) is not None and ov == 0
    ]
    if lone_fail:
        print(
            f"  ⚠ {len(lone_fail)} chassis FAILED while ALONE in the pipeline "
            f"({', '.join(c.short() for c in lone_fail)}) — concurrency is NOT "
            "the sole cause; serialization alone won't eliminate failures."
        )
    # Concurrency only implicates itself if FAIL chassis are MORE crowded than
    # SUCCESS chassis. Equal overlap means it doesn't distinguish the outcome.
    fo = [ov for c in fail if (ov := overlaps(c)) is not None]
    so = [ov for c in succ if (ov := overlaps(c)) is not None]
    if fo and so:
        diff = sum(fo) / len(fo) - sum(so) / len(so)
        if diff >= 0.5:
            print(
                f"  → FAIL overlap exceeds SUCCESS by {diff:.1f} peers — "
                "concurrency may be a factor; serialization worth testing."
            )
        else:
            print(
                "  → FAIL and SUCCESS overlap are similar — concurrency does NOT "
                "distinguish outcome in this window (failures look inherent)."
            )

    # Root-cause signal: does the BYOL↔PAYG license mismatch explain failures?
    # NOTE: on-failure diagnostics are only captured for FAILED chassis, so a
    # SUCCESS chassis never has a dump to inspect — its absence is NOT evidence.
    fail_mm = sum(1 for c in fail if c.license_mismatch)
    print()
    print("License-mismatch (BYOL↔PAYG) root-cause signal:")
    if fail:
        print(
            f"  FAIL chassis whose diagnostic shows SYSTEM_LICENSE_MISMATCH: "
            f"{fail_mm}/{len(fail)}"
        )
        if fail_mm == len(fail):
            print(
                "  → every failure carries the BYOL↔PAYG mismatch. CAUTION: "
                "%VDAEMON-6 is severity=informational and all edges boot the same "
                "BYOL image, so this line likely appears on SUCCESSES too (benign "
                "constant). A causal read is unconfirmed — capture success-side "
                "license state to disambiguate."
            )
    print(
        "  (Diagnostics are dumped only on FAILURE, so SUCCESS chassis show no "
        "mismatch line by construction — proving the ⇔ needs capturing license "
        "state on success too.)"
    )

    if serntpres:
        print()
        print(f"vBond SERNTPRES teardowns seen in diagnostics ({len(serntpres)}):")
        for t in serntpres:
            print(f"  {t}")

    print()
    print(
        "Read (confirmed 2026-07-08, wait-through-failure diagnostic run):\n"
        "  * FLAP is the SUCCESS signal, not instability. Winning chassis go\n"
        "    0→1→0→2: the connection comes up, vBond tears it down (SERNTPRES —\n"
        "    serial not yet propagated to the controllers), then it rebuilds to 2\n"
        "    once the serial lands. These take ~5-6 min (path tok→csr→installed).\n"
        "  * certinstallfailed is TERMINAL for a chassis. Failing chassis reach\n"
        "    0→1, never flap, and hit FAILED in ~1.5 min (path tok→csr→FAILED);\n"
        "    holding the same chassis longer does NOT recover it — a fresh chassis\n"
        "    is required. Pre-activate validity is always 'valid' (ruled out).\n"
        "  * Therefore the lever is the certinstallfailed DRAW RATE (the vManage\n"
        "    BYOL↔PAYG race), not how long we wait. Fast-bail-and-regenerate is\n"
        "    correct; reducing bad draws is the open problem."
    )


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
