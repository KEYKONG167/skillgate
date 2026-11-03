import pytest

from skillgate import GateError
from conftest import write_cases


def first(ids, n):
    return set(ids[:n])


@pytest.fixture
def base(ws):
    """Baseline passes half of every pool."""
    skill = ws.skill("base", first(ws.practice, 10) | first(ws.sealed, 30))
    gate = ws.gate()
    out = gate.set_baseline(skill)
    assert out["practice"] == {"n": 20, "passes": 10} and out["sealed_cases"] == 60
    return gate, out["version"]


def test_a_clearly_better_candidate_is_promoted(ws, base):
    gate, v0 = base
    better = ws.skill("better", first(ws.practice, 15) | first(ws.sealed, 50))
    d = gate.check(better)
    assert d.promoted and d.stage == "sealed" and d.champion == v0
    assert d.practice == {"n": 20, "champion": 10, "candidate": 15}
    assert gate.champion() == d.version and gate.remaining_budget() == 4
    exam = gate.report(refresh=False)["exams"][0]
    assert (exam["b"], exam["c"], exam["ran"], exam["reason"]) == (20, 0, 60, "better")


def test_practice_prescreen_saves_the_sealed_budget(ws, base):
    gate, v0 = base
    d = gate.check(ws.skill("same-on-practice", first(ws.practice, 10) | first(ws.sealed, 60)))
    assert not d.promoted and d.stage == "practice" and gate.remaining_budget() == 5
    assert ws.ran(gate, d.version) == 0  # never touched the sealed cases


def test_a_clearly_worse_candidate_stops_early(ws, base):
    gate, v0 = base
    worse = ws.skill("worse", first(ws.practice, 12))  # better on practice, fails every sealed case
    d = gate.check(worse)
    assert not d.promoted and d.stage == "sealed"
    exam = gate.report(refresh=False)["exams"][0]
    assert exam["reason"] == "worse" and exam["ran"] < 60
    assert ws.ran(gate, d.version) == exam["ran"]


def test_a_lucky_looking_candidate_is_not_promoted(ws, base):
    gate, v0 = base
    # 3 wins, 1 loss on the sealed cases: ahead, but that is what a coin does too
    passes = first(ws.practice, 11) | (first(ws.sealed, 30) - {ws.sealed[0]}) | set(ws.sealed[30:33])
    d = gate.check(ws.skill("lucky", passes))
    assert not d.promoted and d.stage == "sealed"
    assert gate.report(refresh=False)["exams"][0]["reason"] in ("not_significant", "cannot_win", "not_ahead")
    assert gate.champion() == v0


def test_same_question_same_answer(ws, base):
    gate, v0 = base
    better = ws.skill("better", first(ws.practice, 15) | first(ws.sealed, 50))
    worse = ws.skill("worse", first(ws.practice, 5))
    assert gate.check(worse).stage == "practice"
    again = gate.check(worse)
    assert again.stage == "repeat" and not again.promoted and gate.remaining_budget() == 5
    promoted = gate.check(better)
    assert gate.check(better).stage == "unchanged"  # it is the champion now
    assert promoted.promoted


def test_budget_runs_out(ws, base):
    gate, v0 = base
    ws.write_config(budget=1)
    gate = ws.gate()
    gate.check(ws.skill("a", first(ws.practice, 12)))
    with pytest.raises(GateError, match="budget"):
        gate.check(ws.skill("b", first(ws.practice, 13)))


def test_below_baseline_is_rejected(ws):
    new = [f"n{i:03d}" for i in range(40)]
    gate = ws.gate()
    v0 = gate.set_baseline(ws.skill("base", first(ws.practice, 10) | first(ws.sealed, 30) | set(new)))["version"]
    v1 = gate.check(ws.skill("v1", first(ws.practice, 15) | first(ws.sealed, 50))).version
    assert gate.champion() == v1  # the new cases are not in the pool yet
    write_cases(ws.root / "sealed" / "cases.jsonl", ws.sealed + new)  # real-work cases arrive
    v2 = gate.check(ws.skill("v2", first(ws.practice, 16) | first(ws.sealed, 58)))
    exam = gate.report(refresh=False)["exams"][-1]
    assert not v2.promoted and exam["reason"] == "below_baseline"  # beats v1, but not the original on all cases
    assert exam["b"] == 8 and exam["c"] == 0


def test_the_agent_side_never_sees_sealed_numbers(ws, base):
    gate, v0 = base
    gate.check(ws.skill("better", first(ws.practice, 15) | first(ws.sealed, 50)))
    practice_side = (ws.root / ".skillgate" / "ledger.jsonl").read_text(encoding="utf-8")
    assert "p_better" not in practice_side and '"b"' not in practice_side and "passes\": 30" not in practice_side
    status = gate.status()
    assert set(status) == {"baseline", "champion", "trust_level", "remaining_budget", "decisions"}


def test_trust_is_earned_and_reported(ws):
    gate = ws.gate()
    gate.set_baseline(ws.skill("base", set(ws.practice) | set(ws.sealed)))
    assert gate.status()["trust_level"] == "spot_check"  # 60/60: at least 94% with 95% confidence
    write_cases(ws.root / "sealed" / "cases.jsonl", ws.sealed + [f"x{i}" for i in range(20)])
    r = gate.report()
    assert r["sealed"]["n"] == 80 and r["sealed"]["passes"] == 60 and r["trust_level"] == "human_review"


def test_errors_count_as_fails_and_are_not_cached(ws, base):
    gate, v0 = base
    d = gate.check(ws.skill("crashy", first(ws.practice, 20), "crash"))
    assert d.stage == "practice" and d.practice["candidate"] == 0
    assert not list(gate.practice_runner.cache_dir.glob(f"{d.version}/*.json"))


def test_slow_cases_time_out(ws, base):
    gate, v0 = base
    res = gate.practice_runner.result(gate.store.freeze(ws.skill("slow", ws.practice, "slow")), gate._practice_cases()[0])
    assert not res.passed and "timed out" in res.error


def test_verify_and_export(ws, base):
    gate, v0 = base
    assert all(ok for _, ok, _ in gate.verify())
    out = gate.export(ws.root / "deployed")
    assert (out / "passes.txt").is_file()
    with pytest.raises(GateError):
        gate.export(ws.root / "deployed")
    (gate.store.path(v0) / "passes.txt").write_text("tampered", encoding="utf-8")
    assert not all(ok for _, ok, _ in gate.verify())


def test_baseline_only_once(ws, base):
    gate, v0 = base
    with pytest.raises(GateError, match="already"):
        gate.set_baseline(ws.root / "skills" / "base")
