import pytest

from utils import netmiko


class _FakeConn:
    """Minimal stand-in for a Netmiko connection.

    ``config_mode`` replays a scripted list of behaviours (an Exception to raise
    for "not ready", or None for "entered config mode"). ``exit_config_mode``
    calls (the synchronized leave after a successful probe) are counted.
    """

    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.config_mode_calls = 0
        self.exit_config_mode_calls = 0

    def config_mode(self, *args, **kwargs):
        self.config_mode_calls += 1
        behaviour = self._behaviours.pop(0)
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour or ""

    def exit_config_mode(self, *args, **kwargs):
        self.exit_config_mode_calls += 1
        return ""


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    # Don't actually sleep between probes.
    monkeypatch.setattr(netmiko.out, "spinner_wait", lambda *a, **k: None)


def _ready(conn, timeout=600, poll=20):
    return netmiko.wait_for_config_ready(
        conn,
        config_mode_command="config-transaction",
        poll_interval=poll,
        timeout=timeout,
    )


def test_gate_passes_immediately_when_device_ready():
    conn = _FakeConn([None])

    assert _ready(conn) is True
    assert conn.config_mode_calls == 1
    # After a successful probe we leave config mode in a synchronized way.
    assert conn.exit_config_mode_calls == 1


def test_gate_retries_until_config_mode_reachable():
    conn = _FakeConn(
        [
            ValueError("Failed to enter configuration mode."),
            ValueError("Failed to enter configuration mode."),
            None,
        ]
    )

    assert _ready(conn) is True
    assert conn.config_mode_calls == 3
    # Only the successful probe triggers a config-mode exit.
    assert conn.exit_config_mode_calls == 1


def test_gate_returns_false_after_timeout(monkeypatch):
    # 1st call sets the deadline (1000 + 600 = 1600); after the first failed
    # probe the clock has jumped past it, so the loop exits deterministically
    # without real time passing.
    ticks = iter([1000.0, 2000.0])
    monkeypatch.setattr(netmiko.time, "monotonic", lambda: next(ticks))

    conn = _FakeConn([ValueError("Failed to enter configuration mode.")] * 5)

    assert _ready(conn, timeout=600) is False
    # Only the first probe runs before the deadline check trips.
    assert conn.config_mode_calls == 1


def test_gate_does_not_exit_config_mode_when_never_ready(monkeypatch):
    ticks = iter([0.0, 0.0, 999.0])
    monkeypatch.setattr(netmiko.time, "monotonic", lambda: next(ticks))

    conn = _FakeConn([ValueError("nope")] * 5)

    assert _ready(conn, timeout=1) is False
    assert conn.exit_config_mode_calls == 0
