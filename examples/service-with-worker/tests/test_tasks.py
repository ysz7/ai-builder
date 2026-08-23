"""The tasks themselves, called the way anything else calls a function."""

from work.tasks import build_report, sweep_reports


def test_a_report_totals_its_lines() -> None:
    assert build_report(2) == {"order_id": 2, "lines": 3, "total": 12}


def test_sweeping_counts_the_hours_it_covers() -> None:
    assert sweep_reports(7200) == 2
    assert sweep_reports(0) == 0
