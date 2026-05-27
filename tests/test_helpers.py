from utils import manager_api_status, run_stats


def test_format_duration():
    assert run_stats._format_duration(3.2) == "3s"
    assert run_stats._format_duration(65) == "1m 5s"
    assert run_stats._format_duration(3661) == "1h 1m 1s"


def test_build_table_aligns_values_and_empty_rows():
    assert manager_api_status._build_table(["Name"], [["edge1"]]) == [
        "+-------+",
        "| Name  |",
        "+-------+",
        "| edge1 |",
        "+-------+",
    ]


def test_format_ratio_handles_missing_values():
    assert manager_api_status._format_ratio(None, None) == "-"
    assert manager_api_status._format_ratio(1, 2) == "1/2"
