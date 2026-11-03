"""The gate: decides whether a candidate skill version may replace the current one.

    baseline   freeze the starting version and grade it on every case (once)
    check      1. freeze the candidate (hash-named; later edits make a new version)
               2. practice prescreen: it must do better than the champion on the
                  practice cases, which costs no sealed budget
               3. sealed exam, paired with the champion on the same cases, in batches;
                  stops early when the candidate is clearly worse or cannot win
               4. promote only if it is significantly better than the champion and
                  not below the original baseline
    status     what the agent may see: champion, decisions, budget, trust level
    report     what the human sees: sealed numbers behind every decision

Two ledgers: the practice side (anyone may read it) and the sealed side (keep it
with the sealed cases). `check` only ever returns promoted / rejected, the stage,
and the remaining budget, so sealed results do not leak back to whoever edits the skill.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from skillgate.cases import Case, load_cases
from skillgate.config import Config, load_config
from skillgate.ledger import Ledger
from skillgate.runner import Result, Runner
from skillgate.stats import p_better, p_worse, wilson_lower
from skillgate.versions import Store, TamperedError

HUMAN_REVIEW = "human_review"


class GateError(RuntimeError):
    pass


@dataclass
class Decision:
    version: str
    champion: str  # the champion the candidate was compared with
    promoted: bool
    stage: str  # "unchanged", "repeat", "practice" or "sealed"
    remaining_budget: int
    practice: dict | None = None  # {"n", "champion", "candidate"} pass counts

    def to_dict(self) -> dict:
        return asdict(self)


def _passes(results: dict[str, Result]) -> int:
    return sum(r.passed for r in results.values())


def _digest(results: dict[str, Result]) -> str:
    """Fingerprint of who passed what, so the ledger pins down the exact results."""
    raw = json.dumps(sorted((k, r.passed) for k, r in results.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def level_for(passes: int, n: int, cfg: Config) -> tuple[str, float]:
    lower = wilson_lower(passes, n)
    name = HUMAN_REVIEW
    for lv in cfg.levels:  # sorted from the lowest bar to the highest
        if n >= lv.min_cases and lower >= lv.min_pass_rate:
            name = lv.name
    return name, lower


class Gate:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg.state / "versions")
        self.ledger = Ledger(cfg.state / "ledger.jsonl")
        self.sealed_ledger = Ledger(cfg.sealed_state / "ledger.jsonl")
        self.practice_runner = Runner(cfg, self.store, cfg.state / "cache")
        self.sealed_runner = Runner(cfg, self.store, cfg.sealed_state / "cache")

    @classmethod
    def load(cls, config: Path | str = "skillgate.toml") -> "Gate":
        return cls(load_config(config))

    # -- state, derived from the ledgers --------------------------------------

    def baseline_version(self) -> str | None:
        return next((e["payload"]["version"] for e in self.ledger.entries("baseline")), None)

    def champion(self) -> str | None:
        champ = self.baseline_version()
        for e in self.ledger.entries("decision"):
            if e["payload"]["promoted"]:
                champ = e["payload"]["version"]
        return champ

    def remaining_budget(self) -> int:
        return self.cfg.budget - sum(1 for _ in self.sealed_ledger.entries("exam"))

    def decisions(self) -> list[dict]:
        return [e["payload"] for e in self.ledger.entries("decision")]

    def _require_champion(self) -> str:
        champ = self.champion()
        if champ is None:
            raise GateError("no baseline yet: run `skillgate baseline <skill-dir>` first")
        return champ

    def _practice_cases(self) -> list[Case]:
        return load_cases(self.cfg.practice_cases) if self.cfg.practice_cases else []

    def _sealed_cases(self) -> list[Case]:
        cases = load_cases(self.cfg.sealed_cases)
        if not cases:
            raise GateError(f"the sealed pool is empty: {self.cfg.sealed_cases}")
        # A fixed shuffle, so the early batches are a fair sample of the whole exam.
        return sorted(cases, key=lambda c: hashlib.sha256(f"{self.cfg.seed}:{c.id}".encode("utf-8")).hexdigest())

    # -- actions --------------------------------------------------------------

    def set_baseline(self, skill_dir: Path) -> dict:
        if self.baseline_version() is not None:
            raise GateError(f"a baseline is already set ({self.baseline_version()}); use a fresh state directory to start over")
        sealed = self._sealed_cases()
        vid = self.store.freeze(Path(skill_dir))
        practice = self._practice_cases()
        p = self.practice_runner.results(vid, practice)
        s = self.sealed_runner.results(vid, sealed)
        self.sealed_ledger.append("record", {"version": vid, "n": len(s), "passes": _passes(s), "results": _digest(s), "why": "baseline"})
        self.ledger.append("baseline", {"version": vid, "practice": {"n": len(p), "passes": _passes(p)}})
        return {"version": vid, "practice": {"n": len(p), "passes": _passes(p)}, "sealed_cases": len(s)}

    def check(self, candidate_dir: Path) -> Decision:
        champ = self._require_champion()
        vid = self.store.freeze(Path(candidate_dir))
        if vid == champ:
            return Decision(vid, champ, False, "unchanged", self.remaining_budget())
        for d in self.decisions():
            if d["version"] == vid and d["champion"] == champ:  # same question, same answer; no budget spent
                return Decision(vid, champ, d["promoted"], "repeat", self.remaining_budget(), d.get("practice"))

        practice = self._practice_cases()
        summary = None
        if practice:
            old = self.practice_runner.results(champ, practice)
            new = self.practice_runner.results(vid, practice)
            summary = {"n": len(practice), "champion": _passes(old), "candidate": _passes(new)}
            ok = {"better": summary["candidate"] > summary["champion"], "not_worse": summary["candidate"] >= summary["champion"], "off": True}[self.cfg.prescreen]
            if not ok:
                return self._decide(Decision(vid, champ, False, "practice", self.remaining_budget(), summary))

        if self.remaining_budget() <= 0:
            raise GateError("the sealed budget is used up; add new sealed cases and raise [sealed] budget, or start a new gate")
        exam = self._exam(vid, champ)
        self.sealed_ledger.append("exam", exam)
        return self._decide(Decision(vid, champ, exam["promoted"], "sealed", self.remaining_budget(), summary))

    def _decide(self, d: Decision) -> Decision:
        self.ledger.append("decision", d.to_dict())
        return d

    def _exam(self, vid: str, champ: str) -> dict:
        cfg, cases = self.cfg, self._sealed_cases()
        n = len(cases)
        b = c = done = 0
        stopped = None
        cand_all: dict[str, Result] = {}
        for start in range(0, n, cfg.batch):
            chunk = cases[start : start + cfg.batch]
            new = self.sealed_runner.results(vid, chunk)
            old = self.sealed_runner.results(champ, chunk)
            cand_all.update(new)
            for case in chunk:
                b += new[case.id].passed and not old[case.id].passed
                c += old[case.id].passed and not new[case.id].passed
            done += len(chunk)
            left = n - done
            if left == 0:
                break
            if cfg.stop_if_worse and p_worse(b, c) <= cfg.alpha:
                stopped = "worse"
            elif p_better(b + left, c) > cfg.alpha:
                stopped = "cannot_win"  # even winning every remaining case would not be enough
            elif done >= cfg.futility_after * n and b <= c:
                stopped = "not_ahead"
            if stopped:
                break

        p = p_better(b, c)
        record = {"version": vid, "champion": champ, "n": n, "ran": done, "b": b, "c": c, "p_better": p, "stopped": stopped, "results": _digest(cand_all)}
        if stopped:
            return {**record, "promoted": False, "reason": stopped}
        base = self.sealed_runner.results(self.baseline_version(), cases)
        record.update(passes=_passes(cand_all), baseline_passes=_passes(base))
        if p > cfg.alpha:
            return {**record, "promoted": False, "reason": "not_significant"}
        if record["passes"] < record["baseline_passes"]:
            return {**record, "promoted": False, "reason": "below_baseline"}
        return {**record, "promoted": True, "reason": "better"}

    def _champion_record(self, champ: str) -> dict | None:
        rec = None
        for e in self.sealed_ledger.entries():
            p = e["payload"]
            if e["kind"] == "record" and p["version"] == champ:
                rec = {"n": p["n"], "passes": p["passes"]}
            elif e["kind"] == "exam" and p["version"] == champ and p["promoted"]:
                rec = {"n": p["n"], "passes": p["passes"]}
        return rec

    def status(self) -> dict:
        champ = self._require_champion()
        rec = self._champion_record(champ)
        level = level_for(rec["passes"], rec["n"], self.cfg)[0] if rec else HUMAN_REVIEW
        return {
            "baseline": self.baseline_version(),
            "champion": champ,
            "trust_level": level,
            "remaining_budget": self.remaining_budget(),
            "decisions": self.decisions(),
        }

    def report(self, refresh: bool = True) -> dict:
        """The human's view, with sealed numbers. With refresh, the champion is first
        graded on sealed cases added since its last record (cases from real work)."""
        champ = self._require_champion()
        if refresh:
            res = self.sealed_runner.results(champ, self._sealed_cases())
            rec = self._champion_record(champ)
            if rec is None or rec["n"] != len(res) or rec["passes"] != _passes(res):
                self.sealed_ledger.append("record", {"version": champ, "n": len(res), "passes": _passes(res), "results": _digest(res), "why": "refresh"})
        rec = self._champion_record(champ) or {"n": 0, "passes": 0}
        level, lower = level_for(rec["passes"], rec["n"], self.cfg)
        return {
            "champion": champ,
            "baseline": self.baseline_version(),
            "sealed": {**rec, "pass_rate": rec["passes"] / rec["n"] if rec["n"] else None, "pass_rate_lower": lower},
            "trust_level": level,
            "remaining_budget": self.remaining_budget(),
            "exams": [e["payload"] for e in self.sealed_ledger.entries("exam")],
        }

    def export(self, dest: Path) -> Path:
        dest = Path(dest)
        if dest.exists():
            raise GateError(f"{dest} already exists; pick a new path")
        shutil.copytree(self.store.path(self._require_champion()), dest)
        return dest

    def verify(self) -> list[tuple[str, bool, str]]:
        out = [("practice ledger", *self.ledger.verify()), ("sealed ledger", *self.sealed_ledger.verify())]
        for vid in self.store.ids():
            try:
                self.store.path(vid)
                out.append((f"version {vid}", True, "unchanged"))
            except TamperedError as e:
                out.append((f"version {vid}", False, str(e)))
        return out
