"""Every script in ``examples/`` runs from any working directory, and ``examples/data`` works with the CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from askcert import AskCert, RuleSet
from askcert.cli import main

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
DATA = EXAMPLES / "data"

# One line that proves each example did its job (regular expressions, matched per line).
KEY_LINE = {
    "01_basic_boolean.py": r"^never\s+given \{\}\s+-> FALSE$",
    "02_decision_certificates.py": r"^certificate : \{'is_owner': True, 'is_verified': True\}$",
    "03_missing_information.py": r"^decided: TRUE because \{'has_id': True, 'has_ticket': True\}$",
    "04_business_policy.py": r"^  refund_approved = FALSE$",
    "05_llm_reasoning.py": r"^  FALSE because \{'is_resident': False\}$",
    "06_legal_reasoning.py": r"^s3 alone \(long tenancy, 90 days passed\): TRUE ",
    "07_batch_certification.py": r"^certified 729 evidence bodies: "
    r"\{'FALSE': 601, 'TRUE': 5, 'UNKNOWN': 123\}$",
}
SCRIPTS = sorted(p.name for p in EXAMPLES.glob("[0-9][0-9]_*.py"))


def run_example(name: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_every_example_has_a_key_line():
    assert sorted(KEY_LINE) == SCRIPTS
    assert len(SCRIPTS) == 7


@pytest.mark.parametrize("name", SCRIPTS)
def test_example_runs_from_a_temp_dir(name, tmp_path):
    proc = run_example(name, tmp_path)
    assert (proc.returncode, proc.stderr) == (0, "")
    assert re.search(KEY_LINE[name], proc.stdout, re.MULTILINE), proc.stdout


@pytest.mark.parametrize("name", [n for n in SCRIPTS if not n.startswith("07")])  # 07 prints a timing line
def test_example_output_is_deterministic(name, tmp_path):
    assert run_example(name, tmp_path).stdout == run_example(name, tmp_path).stdout


def test_example_07_timing_line_is_the_only_variable_line(tmp_path):
    out = run_example("07_batch_certification.py", tmp_path).stdout.splitlines()
    assert out[-1].startswith("timing (varies by machine)")
    assert out[:-1] == run_example("07_batch_certification.py", tmp_path).stdout.splitlines()[:-1]


# -- examples/data through the CLI ---------------------------------------------------------------
RULES_FILE = str(DATA / "eligibility_rules.json")


def test_data_validate(capsys):
    assert main(["validate", "--rules", RULES_FILE]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rules"] == ["academic_ok", "financial_ok", "eligible"]
    assert out["atoms"] == ["enrolled", "gpa_ok", "has_sanction", "income_ok", "on_waiver", "resident"]


def test_data_certify_evidence_is_unknown_with_two_relevant_unknowns(capsys):
    argv = [
        "certify",
        "--rules",
        RULES_FILE,
        "--goal",
        "eligible",
        "--evidence",
        str(DATA / "eligibility_evidence.json"),
    ]
    assert main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    evidence = json.loads((DATA / "eligibility_evidence.json").read_text(encoding="utf-8"))
    assert result == AskCert(RuleSet.load(RULES_FILE)).certify("eligible", evidence).to_dict()
    assert result["status"] == "UNKNOWN"
    assert result["relevant_unknowns"] == ["income_ok", "on_waiver"]


def test_data_batch_matches_library(capsys):
    argv = ["batch", "--rules", RULES_FILE, "--goal", "eligible", "--cases", str(DATA / "cases.jsonl")]
    assert main(argv) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    cases = [
        json.loads(line)
        for line in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows == [r.to_dict() for r in AskCert(RuleSet.load(RULES_FILE)).certify_many("eligible", cases)]
    assert [row["status"] for row in rows] == ["TRUE", "UNKNOWN", "UNKNOWN", "FALSE", "FALSE", "UNKNOWN"]


def test_data_evaluate(capsys):
    assert main(["evaluate", "--rules", RULES_FILE, "--goal", "eligible"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "UNKNOWN"
