"""Lightweight runtime statistics for automation runs."""

from __future__ import annotations

import atexit
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class RunStats:
    command: str
    started_at: float = field(default_factory=time.perf_counter)
    phase_seconds: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    _printed: bool = False

    def add_phase(self, name: str, seconds: float) -> None:
        self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + seconds

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    @property
    def total_seconds(self) -> float:
        return time.perf_counter() - self.started_at


_current: RunStats | None = None
_out = None


def start(command: str, out) -> None:
    global _current, _out
    _current = RunStats(command=command)
    _out = out


def disable() -> None:
    global _current, _out
    _current = None
    _out = None


def increment(name: str, amount: int = 1) -> None:
    if _current:
        _current.increment(name, amount)


@contextmanager
def phase(name: str) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        yield
    finally:
        if _current:
            _current.add_phase(name, time.perf_counter() - started_at)


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _display_name(name: str) -> str:
    return name.replace("_", " ")


def print_summary() -> None:
    if not _current or not _out or _current._printed:
        return
    _current._printed = True

    _out.header("Run Summary")
    _out.info(f"Command: {_current.command}")
    _out.info(f"Total runtime: {_format_duration(_current.total_seconds)}")

    if _current.phase_seconds:
        slowest = sorted(
            _current.phase_seconds.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        top = ", ".join(
            f"{_display_name(name)} {_format_duration(seconds)}"
            for name, seconds in slowest[:3]
        )
        _out.info(f"Longest phases: {top}")

    if _current.counters:
        counters = ", ".join(
            f"{_display_name(name)}={value}"
            for name, value in sorted(_current.counters.items())
        )
        _out.info(f"Counters: {counters}")


atexit.register(print_summary)
