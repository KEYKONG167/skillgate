import json
from pathlib import Path

import pytest

from skillgate import Gate

RUNNER = '''\
import json, sys, time
from pathlib import Path
skill, case_id = Path(sys.argv[1]), sys.argv[2]
if (skill / "crash").exists():
    sys.exit(3)
if (skill / "slow").exists():
    time.sleep(5)
print("some log line")
print(json.dumps({"pass": case_id in set((skill / "passes.txt").read_text().split())}))
'''


def write_cases(path: Path, ids) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"id": i}) + "\n" for i in ids), encoding="utf-8")
    return path


class Workspace:
    """A gate whose skills are just lists of the case ids they pass."""

    def __init__(self, root: Path):
        self.root = root
        (root / "run.py").write_text(RUNNER, encoding="utf-8")
        self.practice = [f"p{i:02d}" for i in range(20)]
        self.sealed = [f"s{i:03d}" for i in range(60)]
        write_cases(root / "practice.jsonl", self.practice)
        write_cases(root / "sealed" / "cases.jsonl", self.sealed)
        self.write_config()

    def write_config(self, budget: int = 5, extra: str = "", **rule):
        rules = "".join(f"{k} = {json.dumps(v)}\n" for k, v in {"batch": 10, **rule}.items())
        (self.root / "skillgate.toml").write_text(
            'run = ["{python}", "run.py", "{skill}", "{case_id}"]\n'
            "jobs = 4\ntimeout = 3\n"
            '[practice]\ncases = "practice.jsonl"\n'
            f'[sealed]\ncases = "sealed/cases.jsonl"\nbudget = {budget}\n'
            f"[rule]\n{rules}{extra}",
            encoding="utf-8",
        )

    def skill(self, name: str, passes, *flags: str) -> Path:
        d = self.root / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "passes.txt").write_text("\n".join(sorted(passes)), encoding="utf-8")
        for f in flags:
            (d / f).write_text("", encoding="utf-8")
        return d

    def gate(self) -> Gate:
        return Gate.load(self.root / "skillgate.toml")

    def ran(self, gate: Gate, vid: str) -> int:
        """How many sealed cases this version has actually been run on."""
        return sum(1 for _ in gate.sealed_runner.cache_dir.glob(f"{vid}/*.json"))


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(tmp_path)
