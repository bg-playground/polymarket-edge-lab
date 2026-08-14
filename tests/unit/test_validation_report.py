from polymarket_edge_lab.validation.report import ValidationReport


def test_clean_report() -> None:
    report = ValidationReport(10, 10, 0, 0)
    assert report.is_clean is True


def test_duplicate_report_is_not_clean() -> None:
    report = ValidationReport(10, 9, 1, 0)
    assert report.is_clean is False
