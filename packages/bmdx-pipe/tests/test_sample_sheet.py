"""Genomic samples traced to the study's animals (ADR-0032)."""

import openpyxl

from bmdx_pipe.experiment_metadata import describe_from_structure
from bmdx_pipe.file_integrator import FileFingerprint, fingerprint_xlsx
from bmdx_pipe.sample_sheet import read_sample_sheet, resolve_sample
from bmdx_pipe.study_structure import StudyStructure, check_against_structure


def _sheet(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "per_sample_summary"
    ws.append(["Sample name", "fastq_file", "Animal ID", "Tissue"])
    ws.append(["Plate1-101", "Plate1-101.fastq.gz", 101, "Liver"])
    ws.append(["Plate1-102", "Plate1-102.fastq.gz", 102, "Liver"])
    ws.append(["Plate5-901", "Plate5-901.fastq.gz", 111, "Kidney"])
    wb.save(path)
    return str(path)


def _microarray_list(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Sample Number", "GeneChip File Name", "Sample Sequence", " Animal #"])
    ws.append([None, None, None, None])
    ws.append([1, "001-051914-MW_(Rat230_2).CEL", 1, 174])
    wb.save(path)
    return str(path)


ST = StudyStructure(
    sexes=["Female", "Male"], dose_groups=[0.0, 4.0],
    animals={"101": {"sex": "Male", "dose": 0.0}, "102": {"sex": "Male", "dose": 4.0},
             "111": {"sex": "Female", "dose": 0.0}})


def test_a_sheet_is_found_by_its_columns(tmp_path):
    m = read_sample_sheet(_sheet(tmp_path / "anything.xlsx"))
    assert m["plate1-101"] == {"sample": "Plate1-101", "animal_id": "101", "tissue": "Liver"}
    m = read_sample_sheet(_microarray_list(tmp_path / "list.xlsx"))
    assert resolve_sample("001-051914-MW_(Rat230_2).CEL", m, set())["animal_id"] == "174"
    fp = fingerprint_xlsx("x", "per_sample_summary.xlsx", str(tmp_path / "anything.xlsx"), "t")
    assert (fp.platform, fp.data_type) == (None, "sample_sheet")


def test_without_a_sheet_only_a_trailing_animal_number_resolves():
    animals = {"1", "116"}
    assert resolve_sample("Plate5-116", {}, animals) == {"animal_id": "116", "tissue": None}
    for name in ("4DR1F10HE_S132_R1_001", "S1P3_G06", "001-051914-MW_(Rat230_2).CEL", "Plate5-117"):
        assert resolve_sample(name, {}, animals) is None


def test_samples_are_checked_against_their_animals(tmp_path):
    st = StudyStructure(**{**ST.__dict__, "samples": read_sample_sheet(_sheet(tmp_path / "s.xlsx"))})
    fp = FileFingerprint(
        file_id="ge", filename="genomic.bm2", file_type="bm2", tier=3, ts_added="t",
        data_type="gene_expression",
        animal_doses={"Plate1-101": 0.0, "Plate1-102": 0.0, "Plate5-901": 0.0, "X-77": 0.0},
        animal_sexes={"Plate1-101": "Male", "Plate1-102": "Male", "Plate5-901": "Male", "X-77": "Male"})
    kinds = {(i.issue_type, i.severity) for i in check_against_structure({"ge": fp}, st)}
    assert kinds == {("sample_dose_mismatch", "error"), ("sample_sex_mismatch", "error"),
                     ("samples_unresolved", "warning")}


def test_a_genomic_experiment_takes_its_sex_and_organ_from_the_samples(tmp_path):
    st = {**ST.__dict__, "samples": read_sample_sheet(_sheet(tmp_path / "s.xlsx"))}
    exps = [{"name": "Liver_X_Male", "treatments": [{"name": "Plate1-101"}, {"name": "Plate1-102"}]}]
    assert describe_from_structure(exps, st)["Liver_X_Male"] == {"sex": "male", "organ": "liver"}
