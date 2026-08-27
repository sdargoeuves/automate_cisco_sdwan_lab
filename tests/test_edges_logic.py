from components import sdwan_edges
from utils import sdwan_config as settings


def _edge(system_ip: str) -> settings.EdgeConfig:
    return settings.EdgeConfig(mgmt_ip=system_ip, system_ip=system_ip)


def test_parse_payg_activity_extracts_chassis_and_tokens():
    activity = """
    PAYG licenses generated:
    - C8K-PAYG-111-222, abcdef123456
    - C8K-PAYG-333-444, 987654fedcba
    """

    assert sdwan_edges._parse_payg_activity(activity) == [
        {"chassis": "C8K-PAYG-111-222", "token": "abcdef123456"},
        {"chassis": "C8K-PAYG-333-444", "token": "987654fedcba"},
    ]


def test_parse_payg_activity_returns_empty_for_unparseable_output():
    assert sdwan_edges._parse_payg_activity("") == []
    assert sdwan_edges._parse_payg_activity("no license data") == []


def test_safe_int_handles_bad_values():
    assert sdwan_edges._safe_int("2") == 2
    assert sdwan_edges._safe_int(None) == 0
    assert sdwan_edges._safe_int("not-a-number") == 0


def test_edges_not_in_fabric_selects_missing_or_low_control(monkeypatch):
    edge1 = _edge("10.0.0.1")
    edge2 = _edge("10.0.0.2")
    edge3 = _edge("10.0.0.3")
    edge_name_by_id = {
        id(edge1): "edge1",
        id(edge2): "edge2",
        id(edge3): "edge3",
    }

    monkeypatch.setattr(
        sdwan_edges,
        "get_edge_health_items",
        lambda _manager: [
            {"system_ip": "10.0.0.1", "control_connections_up": 2},
            {"system_ip": "10.0.0.2", "control_connections_up": 1},
        ],
    )
    monkeypatch.setattr(sdwan_edges.settings, "manager", object())

    assert sdwan_edges._edges_not_in_fabric(
        [edge1, edge2, edge3],
        edge_name_by_id,
    ) == ["edge2", "edge3"]


def test_edges_without_bfd_selects_zero_or_missing_bfd(monkeypatch):
    edge1 = _edge("10.0.0.1")
    edge2 = _edge("10.0.0.2")
    edge3 = _edge("10.0.0.3")
    edge_name_by_id = {
        id(edge1): "edge1",
        id(edge2): "edge2",
        id(edge3): "edge3",
    }

    monkeypatch.setattr(
        sdwan_edges,
        "get_edge_health_items",
        lambda _manager: [
            {"system_ip": "10.0.0.1", "bfd_sessions_up": 1},
            {"system_ip": "10.0.0.2", "bfd_sessions_up": 0},
        ],
    )
    monkeypatch.setattr(sdwan_edges.settings, "manager", object())

    assert sdwan_edges._edges_without_bfd(
        [edge1, edge2, edge3],
        edge_name_by_id,
    ) == ["edge2", "edge3"]


def _stub_transient_retry(monkeypatch, max_attempts=3, wait=0):
    monkeypatch.setattr(
        settings,
        "edge_transient_retry",
        settings.RetrySpec(max_attempts=max_attempts, wait=wait),
        raising=False,
    )
    monkeypatch.setattr(sdwan_edges.out, "spinner_wait", lambda *a, **k: None)
    sdwan_edges._drain_fatal_edges()


def test_transient_error_is_retried_then_succeeds(monkeypatch):
    _stub_transient_retry(monkeypatch)
    calls = []

    def body(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise sdwan_edges.EdgeTransientError("validator not up yet")

    monkeypatch.setattr(sdwan_edges, "_run_edge_automation_body", body)
    sdwan_edges.run_edge_automation(_edge("10.0.0.1"), edge_name="edge1")

    assert len(calls) == 3
    assert sdwan_edges._drain_fatal_edges() == {}


def test_exhausted_transient_budget_becomes_fatal(monkeypatch):
    _stub_transient_retry(monkeypatch, max_attempts=2)

    def body(*args, **kwargs):
        raise sdwan_edges.EdgeTransientError("scp unreachable")

    monkeypatch.setattr(sdwan_edges, "_run_edge_automation_body", body)
    try:
        sdwan_edges.run_edge_automation(_edge("10.0.0.1"), edge_name="edge1")
    except sdwan_edges.EdgeFatalError as exc:
        assert "scp unreachable" in str(exc)
    else:
        raise AssertionError("expected EdgeFatalError")

    assert "edge1" in sdwan_edges._drain_fatal_edges()


def test_fatal_error_is_not_retried(monkeypatch):
    _stub_transient_retry(monkeypatch)
    calls = []

    def body(*args, **kwargs):
        calls.append(1)
        raise sdwan_edges.EdgeFatalError("still on default password")

    monkeypatch.setattr(sdwan_edges, "_run_edge_automation_body", body)
    try:
        sdwan_edges.run_edge_automation(_edge("10.0.0.1"), edge_name="edge1")
    except sdwan_edges.EdgeFatalError:
        pass
    else:
        raise AssertionError("expected EdgeFatalError")

    assert calls == [1]
    assert sdwan_edges._drain_fatal_edges() == {"edge1": "still on default password"}


def test_cert_error_propagates_without_transient_retry(monkeypatch):
    _stub_transient_retry(monkeypatch)
    calls = []

    def body(*args, **kwargs):
        calls.append(1)
        raise sdwan_edges.EdgeCertError("cert did not converge")

    monkeypatch.setattr(sdwan_edges, "_run_edge_automation_body", body)
    try:
        sdwan_edges.run_edge_automation(_edge("10.0.0.1"), edge_name="edge1")
    except sdwan_edges.EdgeCertError:
        pass
    else:
        raise AssertionError("expected EdgeCertError")

    assert calls == [1]
    assert sdwan_edges._drain_fatal_edges() == {}
