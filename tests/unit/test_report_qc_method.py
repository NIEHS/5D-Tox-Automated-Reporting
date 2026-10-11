"""report_qc states plainly when a report cannot follow its published method:
a pinned method profile asking for an unimplemented apical BMD engine is an
error, and so is every BMD that differs from the published one."""

from pipeline.method_profile import pin_profile
from tooling import report_qc


def test_unimplemented_engine_is_an_error(sessions_dir):
    pin_profile("DTXSID1025300", "ntp-5day-2021")  # the BMDS 2.7 era
    qc = report_qc.ReportQC("DTXSID1025300", "X", "NIEHS-02")
    report_qc.check_method(qc)
    [f] = qc.findings
    assert f.check == "method" and f.severity == "error"
    assert any("bmds_2_7_high_dose_drop" in e for e in f.evidence)


def test_implemented_engine_is_clean(sessions_dir):
    pin_profile("DTXSID1020431_rat", "ntp-5day-2025")
    qc = report_qc.ReportQC("DTXSID1020431_rat", "X", None)
    report_qc.check_method(qc)
    assert qc.findings == []
