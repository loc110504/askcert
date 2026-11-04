"""Command-line interface: every subcommand, stdin, exit codes 0 / 2 / 3, error JSON.

Most tests call ``askcert.cli.main`` in-process; a few run ``python -m askcert`` in a subprocess.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import askcert
from askcert import AskCert
from askcert.cli import main

ROOT = Path(__file__).resolve().parents[2]

RULES = {
    "schema_version": "1",
    "atoms": ["a", "b", "c"],
    "rules": {
        "both": {"all": ["a", "b"]},
        "either": {"any": ["a", "b"], "unless": ["c"]},
        "always": {"any": ["a", {"not": "a"}]},
    },
}
EVIDENCE_LINES = [{"a": True, "b": True}, {"a": True}, {}, {"a": False, "b": False}, {"b": None, "c": True}]

# 12 pairs, all x before all y: the ROBDD has about 2**12 nodes, far above --max-nodes 100.
HARD = {"hard": {"any": [{"all": [f"x{i:02d}", f"y{i:02d}"]} for i in range(12)]}}


@pytest.fixture
def rules_file(tmp_path: Path) -> str:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(RULES), encoding="utf-8")
    return str(path)


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    """``run(argv, stdin=None) -> (exit_code, stdout, stderr)`` for in-process ``main``."""

    def _run(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
        if stdin is not None:
            monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8"))))
        code = main(argv)
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        return code, captured.out, captured.err

    return _run


def write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def error_of(err: str) -> dict:
    return json.loads(err)["error"]


# -- success paths ---------------------------------------------------------------------------
def test_version_and_help(run):
    code, out, _ = run(["--version"])
    assert (code, out) == (0, f"askcert {askcert.__version__}\n")
    code, out, _ = run(["--help"])
    assert code == 0
    assert all(name in out for name in ("certify", "evaluate", "batch", "validate"))


def test_validate(run, rules_file):
    code, out, _ = run(["validate", "--rules", rules_file])
    assert code == 0
    assert json.loads(out) == {
        "valid": True,
        "schema_version": "1",
        "rules": ["both", "either", "always"],
        "atoms": ["a", "b", "c"],
    }


def test_validate_accepts_shorthand_and_flat_list(run, tmp_path):
    shorthand = write(tmp_path, "s.json", '{"g": {"all": ["p", "!q"]}}')
    flat = write(tmp_path, "f.json", '{"rules": [{"name": "g", "op": "ALL", "conditions": ["p", "q"]}]}')
    for path in (shorthand, flat):
        code, out, _ = run(["validate", "--rules", path])
        assert code == 0
        assert json.loads(out)["rules"] == ["g"]


def test_certify_decided_and_unknown_equal_library(run, rules_file, tmp_path):
    engine = AskCert(RULES)
    for goal, evidence in [
        ("both", {"a": True, "b": True}),
        ("both", {"a": True}),
        ("either", {"c": True}),
        ("always", {}),
        ("a", {"a": False}),
    ]:
        code, out, _ = run(
            [
                "certify",
                "--rules",
                rules_file,
                "--goal",
                goal,
                "--evidence",
                write(tmp_path, "e.json", json.dumps(evidence)),
            ]
        )
        assert code == 0
        assert json.loads(out) == engine.certify(goal, evidence).to_dict()
        assert out == engine.certify(goal, evidence).to_json(indent=2) + "\n"


def test_certify_unknown_exits_zero_with_unknowns_and_witnesses(run, rules_file):
    code, out, err = run(["certify", "--rules", rules_file, "--goal", "both"])  # no evidence at all
    result = json.loads(out)
    assert (code, err) == (0, "")
    assert result["status"] == "UNKNOWN"
    assert result["relevant_unknowns"] == ["a", "b"]
    assert result["certificate"] is None
    assert result["witnesses"]["true"] != result["witnesses"]["false"]


def test_certify_no_witnesses_and_indent(run, rules_file):
    code, out, _ = run(
        ["certify", "--rules", rules_file, "--goal", "both", "--no-witnesses", "--indent", "0"]
    )
    assert code == 0
    assert out.count("\n") == 1  # --indent 0: one compact line
    assert json.loads(out) == AskCert(RULES).certify("both", witnesses=False).to_dict()
    assert json.loads(out)["witnesses"] is None
    _, out4, _ = run(["certify", "--rules", rules_file, "--goal", "both", "--indent", "4"])
    assert '\n    "goal"' in out4


def test_certify_evidence_from_stdin(run, rules_file):
    code, out, _ = run(
        ["certify", "--rules", rules_file, "--goal", "both", "--evidence", "-"], stdin='{"a": false}'
    )
    assert code == 0
    assert json.loads(out) == AskCert(RULES).certify("both", {"a": False}).to_dict()


def test_evaluate(run, rules_file, tmp_path):
    ev = write(tmp_path, "e.json", '{"a": true}')
    for goal, status in [("both", "UNKNOWN"), ("either", "UNKNOWN"), ("always", "TRUE")]:
        code, out, _ = run(["evaluate", "--rules", rules_file, "--goal", goal, "--evidence", ev])
        assert code == 0
        assert json.loads(out) == {"schema_version": "1", "goal": goal, "status": status}
    _, out, _ = run(
        ["evaluate", "--rules", rules_file, "--goal", "both", "--evidence", "-"], stdin='{"a": false}'
    )
    assert json.loads(out)["status"] == "FALSE"
    _, out, _ = run(["evaluate", "--rules", rules_file, "--goal", "a"])
    assert json.loads(out)["status"] == "UNKNOWN"  # a base atom is a valid goal


def test_batch_file_and_stdin_equal_library(run, rules_file, tmp_path):
    lines = [json.dumps(e) for e in EVIDENCE_LINES]
    text = "\n".join([lines[0], "", lines[1], "   ", *lines[2:]]) + "\n"  # blank lines are skipped
    expected = [r.to_dict() for r in AskCert(RULES).certify_many("both", EVIDENCE_LINES)]
    code, out, err = run(
        ["batch", "--rules", rules_file, "--goal", "both", "--cases", write(tmp_path, "c.jsonl", text)]
    )
    assert (code, err) == (0, "")
    assert [json.loads(line) for line in out.splitlines()] == expected
    assert all(len(line.splitlines()) == 1 for line in out.splitlines())
    code, out_stdin, _ = run(["batch", "--rules", rules_file, "--goal", "both", "--cases", "-"], stdin=text)
    assert (code, out_stdin) == (0, out)


def test_batch_no_witnesses_and_empty_input(run, rules_file, tmp_path):
    cases = write(tmp_path, "c.jsonl", '{"a": true}\n{}\n')
    _, out, _ = run(["batch", "--rules", rules_file, "--goal", "both", "--cases", cases, "--no-witnesses"])
    expected = [r.to_dict() for r in AskCert(RULES).certify_many("both", [{"a": True}, {}], witnesses=False)]
    assert [json.loads(line) for line in out.splitlines()] == expected
    code, out, _ = run(
        ["batch", "--rules", rules_file, "--goal", "both", "--cases", write(tmp_path, "empty.jsonl", "\n\n")]
    )
    assert (code, out) == (0, "")


def test_rules_file_with_bom_and_crlf_cases(run, tmp_path):
    rules = tmp_path / "r.json"
    rules.write_bytes(b"\xef\xbb\xbf" + json.dumps(RULES).encode("utf-8"))
    cases = write(tmp_path, "c.jsonl", '{"a": true}\r\n{"a": false}\r\n')
    code, out, _ = run(["batch", "--rules", str(rules), "--goal", "both", "--cases", cases])
    assert code == 0
    assert [json.loads(x)["status"] for x in out.splitlines()] == ["UNKNOWN", "FALSE"]


# -- exit code 2: invalid input or usage --------------------------------------------------------
@pytest.mark.parametrize(
    ("rules_text", "kind", "needle"),
    [
        ('{"a": {"all": ["b"]}, "b": {"all": ["a"]}}', "RuleError", "cycle"),
        ('{"a": {"nope": ["x"]}}', "RuleError", "nope"),
        ('{"a": "x", "a": "y"}', "RuleError", "duplicate key"),
        ('{"atoms": ["x"], "rules": {"a": {"all": ["x", "y"]}}}', "RuleError", "undefined"),
        ("{not json", "RuleError", "invalid JSON"),
        ('{"schema_version": "2", "rules": {}}', "RuleError", "schema_version"),
    ],
)
def test_invalid_rules_exit_2(run, tmp_path, rules_text, kind, needle):
    path = write(tmp_path, "r.json", rules_text)
    for argv in (
        ["validate", "--rules", path],
        ["certify", "--rules", path, "--goal", "a"],
        ["evaluate", "--rules", path, "--goal", "a"],
    ):
        code, out, err = run(argv)
        assert (code, out) == (2, "")
        assert error_of(err)["type"] == kind
        assert needle in error_of(err)["message"]


def test_unknown_goal_exit_2(run, rules_file):
    code, out, err = run(["certify", "--rules", rules_file, "--goal", "missing"])
    assert (code, out) == (2, "")
    assert error_of(err)["type"] == "RuleError"
    assert "unknown goal" in error_of(err)["message"]


@pytest.mark.parametrize(
    ("evidence", "needle"),
    [
        ('{"zzz": true}', "unknown atom"),
        ('{"both": true}', "derived rule"),
        ('{"a": "yes"}', "True, False or None"),
        ('{"a": 1}', "True, False or None"),
        ('{"a": true, "a": false}', "duplicate key"),
        ("[true]", "JSON object"),
        ("null", "JSON object"),
        ("{oops", "invalid JSON"),
    ],
)
def test_invalid_evidence_exit_2(run, rules_file, tmp_path, evidence, needle):
    code, out, err = run(
        [
            "certify",
            "--rules",
            rules_file,
            "--goal",
            "both",
            "--evidence",
            write(tmp_path, "e.json", evidence),
        ]
    )
    assert (code, out) == (2, "")
    assert error_of(err)["type"] == "EvidenceError"
    assert needle in error_of(err)["message"]


def test_unreadable_files_exit_2(run, rules_file, tmp_path):
    code, _, err = run(["certify", "--rules", str(tmp_path / "missing.json"), "--goal", "a"])
    assert code == 2
    assert error_of(err)["type"] == "RuleError"
    code, _, err = run(
        ["certify", "--rules", rules_file, "--goal", "both", "--evidence", str(tmp_path / "missing.json")]
    )
    assert code == 2
    assert error_of(err)["type"] == "EvidenceError"
    code, _, err = run(["batch", "--rules", rules_file, "--goal", "both", "--cases", str(tmp_path)])  # a dir
    assert code == 2
    bad = tmp_path / "latin1.json"
    bad.write_bytes(b'{"a": "\xe9"}')
    code, _, err = run(["certify", "--rules", rules_file, "--goal", "both", "--evidence", str(bad)])
    assert code == 2
    assert error_of(err)["type"] == "EvidenceError"


def test_batch_bad_json_line_reports_line_number(run, rules_file, tmp_path):
    cases = write(tmp_path, "c.jsonl", '{"a": true}\n\n{"a": tru}\n{"b": false}\n')
    code, out, err = run(["batch", "--rules", rules_file, "--goal", "both", "--cases", cases])
    assert (code, out) == (2, "")  # nothing is printed for a rejected file
    message = error_of(err)["message"]
    assert error_of(err)["type"] == "EvidenceError"
    assert "line 3" in message
    assert "c.jsonl" in message


@pytest.mark.parametrize(
    ("line", "needle"),
    [
        ('{"zzz": true}', "unknown atom"),
        ("[1, 2]", "JSON object"),
        ('{"a": true, "a": true}', "duplicate key"),
        ('{"a": "x"}', "True, False or None"),
    ],
)
def test_batch_bad_line_content_reports_line_number(run, rules_file, tmp_path, line, needle):
    cases = write(tmp_path, "c.jsonl", f'{{"a": true}}\n{{"b": true}}\n{line}\n')
    code, out, err = run(["batch", "--rules", rules_file, "--goal", "both", "--cases", cases])
    assert (code, out) == (2, "")
    assert "line 3" in error_of(err)["message"]
    assert needle in error_of(err)["message"]


def test_batch_bad_line_from_stdin_names_stdin(run, rules_file):
    code, _, err = run(
        ["batch", "--rules", rules_file, "--goal", "both", "--cases", "-"], stdin='{"a": true}\nnot json\n'
    )
    assert code == 2
    assert "<stdin>, line 2" in error_of(err)["message"]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["frobnicate"],
        ["certify", "--goal", "g"],  # --rules missing
        ["certify", "--rules", "r.json"],  # --goal missing
        ["batch", "--rules", "r.json", "--goal", "g"],  # --cases missing
        ["certify", "--rules", "r.json", "--goal", "g", "--max-nodes", "1"],
        ["certify", "--rules", "r.json", "--goal", "g", "--max-nodes", "many"],
        ["certify", "--rules", "r.json", "--goal", "g", "--timeout", "0"],
        ["certify", "--rules", "r.json", "--goal", "g", "--timeout", "nan"],
        ["certify", "--rules", "r.json", "--goal", "g", "--indent", "-1"],
        ["validate", "--rules", "r.json", "--goal", "g"],  # validate takes no goal
    ],
)
def test_usage_errors_exit_2_with_json_on_stderr(run, argv):
    code, out, err = run(argv)
    assert (code, out) == (2, "")
    assert error_of(err)["type"] == "UsageError"


# -- exit code 3: resource limits ---------------------------------------------------------------
@pytest.mark.parametrize("command", ["certify", "evaluate"])
def test_max_nodes_exit_3(run, rules_file, command):
    code, out, err = run([command, "--rules", rules_file, "--goal", "both", "--max-nodes", "2"])
    assert (code, out) == (3, "")
    error = error_of(err)
    assert (error["type"], error["limit"], error["value"]) == ("ResourceLimitExceeded", "max_nodes", 2)


def test_hard_formula_hits_node_limit_and_is_never_unknown(run, tmp_path):
    rules = write(tmp_path, "hard.json", json.dumps(HARD))
    for argv in (
        ["certify", "--goal", "hard", "--max-nodes", "100"],
        ["evaluate", "--goal", "hard", "--max-nodes", "100"],
        ["batch", "--goal", "hard", "--max-nodes", "100", "--cases", write(tmp_path, "c.jsonl", "{}\n")],
    ):
        code, out, err = run([argv[0], "--rules", rules, *argv[1:]])
        assert (code, out) == (3, "")
        assert error_of(err)["limit"] == "max_nodes"
    code, _, _ = run(["evaluate", "--rules", rules, "--goal", "hard"])  # default limit is ample
    assert code == 0


def test_tiny_timeout_exit_3(run, rules_file, tmp_path):
    code, out, err = run(["certify", "--rules", rules_file, "--goal", "both", "--timeout", "1e-9"])
    assert (code, out) == (3, "")
    assert error_of(err)["limit"] == "timeout"
    code, _, err = run(
        [
            "batch",
            "--rules",
            rules_file,
            "--goal",
            "both",
            "--timeout",
            "1e-9",
            "--cases",
            write(tmp_path, "c.jsonl", "{}\n"),
        ]
    )
    assert code == 3
    assert error_of(err)["limit"] == "timeout"


def test_generous_limits_still_succeed(run, rules_file):
    code, _, _ = run(
        ["certify", "--rules", rules_file, "--goal", "both", "--max-nodes", "1000", "--timeout", "60"]
    )
    assert code == 0


# -- real process --------------------------------------------------------------------------------
def cli_process(args: list[str], cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "askcert", *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_subprocess_version_and_certify_via_stdin(rules_file, tmp_path):
    proc = cli_process(["--version"], tmp_path)
    assert (proc.returncode, proc.stdout.strip(), proc.stderr) == (0, f"askcert {askcert.__version__}", "")
    proc = cli_process(
        ["certify", "--rules", rules_file, "--goal", "both", "--evidence", "-"],
        tmp_path,
        stdin='{"a": false}',
    )
    assert (proc.returncode, proc.stderr) == (0, "")
    assert json.loads(proc.stdout) == AskCert(RULES).certify("both", {"a": False}).to_dict()


def test_subprocess_error_exit_codes_without_traceback(rules_file, tmp_path):
    cases = [
        (["certify", "--rules", rules_file, "--goal", "nope"], 2, "RuleError"),
        (
            ["certify", "--rules", rules_file, "--goal", "both", "--max-nodes", "2"],
            3,
            "ResourceLimitExceeded",
        ),
        (["frobnicate"], 2, "UsageError"),
    ]
    for args, code, kind in cases:
        proc = cli_process(args, tmp_path)
        assert proc.returncode == code
        assert proc.stdout == ""
        assert "Traceback" not in proc.stderr
        assert json.loads(proc.stderr)["error"]["type"] == kind
