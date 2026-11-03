import json

import pytest

from skillgate.cases import CaseError, load_cases, materialized
from skillgate.config import ConfigError, load_config
from skillgate.ledger import Ledger
from skillgate.runner import parse_output
from skillgate.versions import Store, TamperedError

from conftest import write_cases


def test_versions_are_frozen_by_content(tmp_path):
    src = tmp_path / "skill"
    (src / "__pycache__").mkdir(parents=True)
    (src / "SKILL.md").write_text("v1", encoding="utf-8")
    (src / "__pycache__" / "x.pyc").write_text("noise", encoding="utf-8")
    store = Store(tmp_path / "store")
    vid = store.freeze(src)
    assert store.freeze(src) == vid and len(vid) == 12
    assert not (store.path(vid) / "__pycache__").exists()
    (src / "SKILL.md").write_text("v2", encoding="utf-8")
    assert store.freeze(src) != vid  # editing the skill makes a new version
    (store.path(vid) / "SKILL.md").write_text("sneaky", encoding="utf-8")
    with pytest.raises(TamperedError):
        store.path(vid)


def test_case_pools(tmp_path):
    pool = tmp_path / "cases.jsonl"
    pool.write_text('{"id": "a", "q": 1}\n\n{"q": 2}\n', encoding="utf-8")
    a, b = load_cases(pool)
    assert (a.id, b.id) == ("a", "line-00003")
    with materialized(b) as path:
        assert json.loads(path.read_text(encoding="utf-8")) == {"q": 2}
    assert not path.exists()
    write_cases(pool, ["x", "x"])
    with pytest.raises(CaseError, match="duplicate"):
        load_cases(pool)
    pool.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(CaseError, match="JSON object"):
        load_cases(pool)

    d = tmp_path / "dirpool"
    for name in ("c1", "c2", ".hidden"):
        (d / name).mkdir(parents=True)
        (d / name / "input.txt").write_text(name, encoding="utf-8")
    cases = load_cases(d)
    assert [c.id for c in cases] == ["c1", "c2"]
    before = cases[0].key
    (d / "c1" / "input.txt").write_text("changed", encoding="utf-8")
    assert load_cases(d)[0].key != before  # changed content is never served from the cache


def test_parse_output_takes_the_last_result_line():
    assert parse_output('{"pass": false}\nlog\n{"pass": true, "detail": "ok"}\n') == {"pass": True, "detail": "ok"}
    assert parse_output('{"pass": "yes"}') is None  # must be a real boolean
    assert parse_output("nothing here") is None


def test_config_errors(tmp_path):
    cfg = tmp_path / "skillgate.toml"
    cfg.write_text('run = "python run.py"\n[sealed]\ncases = "s.jsonl"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="skill"):
        load_config(cfg)
    cfg.write_text('run = "python run.py {skill} {case}"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="sealed"):
        load_config(cfg)
    cfg.write_text('run = "python run.py {skill} {case}"\n[sealed]\ncases = "s.jsonl"\n[rule]\nprescreen = "maybe"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="prescreen"):
        load_config(cfg)
    cfg.write_text('run = "python run.py {skill} {case}"\n[sealed]\ncases = "s/c.jsonl"\n', encoding="utf-8")
    c = load_config(tmp_path)
    assert c.sealed_state == tmp_path / "s" / ".skillgate-sealed" and c.budget == 20 and c.levels[0].name == "spot_check"


def test_ledger_detects_edits(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append("a", {"x": 1})
    ledger.append("b", {"x": 2})
    assert ledger.verify() == (True, "2 entries ok")
    text = (tmp_path / "l.jsonl").read_text(encoding="utf-8").replace('"x": 1', '"x": 9')
    (tmp_path / "l.jsonl").write_text(text, encoding="utf-8")
    ok, msg = Ledger(tmp_path / "l.jsonl").verify()
    assert not ok and "modified" in msg
