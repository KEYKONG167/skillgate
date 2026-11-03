"""skillgate.toml: how to run one case, where the case pools live, and the rules.

Relative paths are resolved against the directory that holds skillgate.toml.
"""

from __future__ import annotations

import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "skillgate.toml"
PRESCREEN = ("better", "not_worse", "off")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Level:
    name: str
    min_pass_rate: float  # compared with the lower end of the 95% Wilson interval, not the raw rate
    min_cases: int


DEFAULT_LEVELS = (Level("spot_check", 0.90, 50), Level("autonomous", 0.98, 200))


@dataclass(frozen=True)
class Config:
    root: Path
    run: tuple[str, ...]
    sealed_cases: Path
    sealed_state: Path
    state: Path
    practice_cases: Path | None = None
    timeout: float = 300.0
    jobs: int = 4
    budget: int = 20
    alpha: float = 0.05
    prescreen: str = "better"
    stop_if_worse: bool = True
    futility_after: float = 0.5
    batch: int = 20
    seed: int = 0
    levels: tuple[Level, ...] = DEFAULT_LEVELS


def _table(raw: dict, key: str) -> dict:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a table")
    return value


def _number(table: dict, key: str, default, kind, lo, hi):
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind is int and not isinstance(value, int)):
        raise ConfigError(f"{key} must be {'an integer' if kind is int else 'a number'}")
    if not lo <= value <= hi:
        raise ConfigError(f"{key} must be between {lo} and {hi}")
    return kind(value)


def load_config(path: Path | str = CONFIG_NAME) -> Config:
    path = Path(path)
    if path.is_dir():
        path = path / CONFIG_NAME
    if not path.is_file():
        raise ConfigError(f"config not found: {path} (run `skillgate init` to create one)")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    root = path.resolve().parent

    run = raw.get("run")
    if isinstance(run, str):
        run = shlex.split(run)
    if not isinstance(run, list) or not run or not all(isinstance(a, str) for a in run):
        raise ConfigError("run must be a command string or a list of strings")
    joined = " ".join(run)
    if "{skill}" not in joined or not ("{case}" in joined or "{case_id}" in joined):
        raise ConfigError("run must contain {skill} and either {case} or {case_id}")

    practice, sealed, rule = _table(raw, "practice"), _table(raw, "sealed"), _table(raw, "rule")
    if "cases" not in sealed:
        raise ConfigError("[sealed] cases is required")
    sealed_cases = root / sealed["cases"]
    sealed_state = root / sealed["state"] if "state" in sealed else sealed_cases.parent / ".skillgate-sealed"
    prescreen = rule.get("prescreen", "better")
    if prescreen not in PRESCREEN:
        raise ConfigError(f"rule.prescreen must be one of {', '.join(PRESCREEN)}")

    levels = []
    for item in raw.get("levels", [{"name": lv.name, "min_pass_rate": lv.min_pass_rate, "min_cases": lv.min_cases} for lv in DEFAULT_LEVELS]):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ConfigError("each [[levels]] entry needs a name")
        levels.append(Level(item["name"], _number(item, "min_pass_rate", None, float, 0.0, 1.0), _number(item, "min_cases", 1, int, 1, 10**9)))

    return Config(
        root=root,
        run=tuple(run),
        sealed_cases=sealed_cases,
        sealed_state=sealed_state,
        state=root / raw.get("state", ".skillgate"),
        practice_cases=root / practice["cases"] if "cases" in practice else None,
        timeout=_number(raw, "timeout", 300.0, float, 1, 86400),
        jobs=_number(raw, "jobs", 4, int, 1, 256),
        budget=_number(sealed, "budget", 20, int, 1, 10**6),
        alpha=_number(rule, "alpha", 0.05, float, 1e-6, 0.5),
        prescreen=prescreen,
        stop_if_worse=bool(rule.get("stop_if_worse", True)),
        futility_after=_number(rule, "futility_after", 0.5, float, 0.0, 1.0),
        batch=_number(rule, "batch", 20, int, 1, 10**6),
        seed=_number(rule, "seed", 0, int, 0, 2**63),
        levels=tuple(sorted(levels, key=lambda lv: lv.min_pass_rate)),
    )


TEMPLATE = """\
# skillgate.toml: how to run one case, where the cases live, and the rules.
# Relative paths are resolved against this file's directory.

# Command that runs ONE skill version on ONE case and prints a JSON line
# like {"pass": true} as its last line of output.
#   {skill}   path of the frozen skill version under test
#   {case}    path of the case (a directory, or a case.json for JSONL pools)
#   {case_id} the case id;  {python} the Python running skillgate
run = "{python} run_case.py --skill {skill} --case {case}"
timeout = 300   # seconds per case; a case that times out counts as a fail
jobs = 4        # cases run in parallel

[practice]
# Cases the skill author (human or agent) may see. Optional.
cases = "cases/practice.jsonl"

[sealed]
# Cases only the gate sees. Keep them where the agent that edits the skill
# cannot read them. Results and the sealed ledger go to `state`
# (default: .skillgate-sealed next to the cases).
cases = "sealed/cases.jsonl"
budget = 20     # how many candidates may take the sealed exam in total

[rule]
alpha = 0.05            # how sure the gate must be that a candidate is better
prescreen = "better"    # on practice: "better", "not_worse" or "off"
stop_if_worse = true    # stop the exam early once the candidate is clearly worse
futility_after = 0.5    # after this share of the exam, stop if the candidate is not ahead
batch = 20              # how often (in cases) the exam checks whether it can stop

# Trust levels, earned from the champion's sealed pass rate (lower end of the
# 95% Wilson interval). Below every level the skill stays at "human_review".
[[levels]]
name = "spot_check"
min_pass_rate = 0.90
min_cases = 50

[[levels]]
name = "autonomous"
min_pass_rate = 0.98
min_cases = 200
"""
