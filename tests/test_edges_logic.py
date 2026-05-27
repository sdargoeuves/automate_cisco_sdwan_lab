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
