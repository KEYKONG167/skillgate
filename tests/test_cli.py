import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "email-triage"


def sg(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "skillgate", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture
def example(tmp_path) -> Path:
    dest = tmp_path / "email-triage"
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns(".skillgate", ".skillgate-sealed", "__pycache__"))
    return dest


def test_the_example_end_to_end(example):
    r = sg(example, "baseline", "skill")
    assert r.returncode == 0, r.stderr
    r = sg(example, "check", "candidates/worse")
    assert r.returncode == 1 and "REJECTED at practice" in r.stdout
    r = sg(example, "check", "candidates/sidegrade")
    assert r.returncode == 1 and "REJECTED" in r.stdout
    r = sg(example, "check", "candidates/better", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["promoted"] and d["stage"] == "sealed"

    status = json.loads(sg(example, "status", "--json").stdout)
    assert status["champion"] == d["version"] and status["trust_level"] == "human_review"
    assert "p_better" not in json.dumps(status)  # the agent-facing view has no sealed numbers
    report = sg(example, "report")
    assert report.returncode == 0 and "promoted" in report.stdout and "rejected" in report.stdout
    assert sg(example, "verify").returncode == 0
    assert sg(example, "export", "deployed").returncode == 0
    assert json.loads((example / "deployed" / "rules.json").read_text(encoding="utf-8")) == json.loads((example / "candidates" / "better" / "rules.json").read_text(encoding="utf-8"))


def test_init_and_errors(tmp_path):
    assert sg(tmp_path, "init").returncode == 0
    assert "run =" in (tmp_path / "skillgate.toml").read_text(encoding="utf-8")
    assert sg(tmp_path, "init").returncode == 2  # never overwrites
    r = sg(tmp_path, "status")
    assert r.returncode == 2 and "baseline" in r.stderr
    r = sg(tmp_path, "-c", "nowhere/skillgate.toml", "status")
    assert r.returncode == 2 and "config not found" in r.stderr
