"""Command line: skillgate init | baseline | check | status | report | export | verify."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skillgate import __version__
from skillgate.cases import CaseError
from skillgate.config import CONFIG_NAME, TEMPLATE, ConfigError
from skillgate.gate import Decision, Gate, GateError
from skillgate.versions import TamperedError

EXIT_OK, EXIT_REJECTED, EXIT_ERROR = 0, 1, 2


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def cmd_init(args) -> int:
    path = Path(args.dir) / CONFIG_NAME
    if path.exists():
        print(f"{path} already exists", file=sys.stderr)
        return EXIT_ERROR
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    print(f"wrote {path}; edit `run` and the case paths, then run `skillgate baseline <skill-dir>`")
    return EXIT_OK


def cmd_baseline(args) -> int:
    out = Gate.load(args.config).set_baseline(Path(args.skill))
    if args.json:
        _print_json(out)
    else:
        p = out["practice"]
        print(f"baseline   {out['version']}")
        if p["n"]:
            print(f"practice   {p['passes']}/{p['n']} passed")
        print(f"sealed     graded on {out['sealed_cases']} cases (numbers in `skillgate report`)")
    return EXIT_OK


def _describe(d: Decision) -> list[str]:
    lines = [f"candidate  {d.version}  (champion {d.champion})"]
    if d.stage == "unchanged":
        return lines + ["result     identical to the champion; nothing to check"]
    if d.stage == "repeat":
        verdict = "PROMOTED" if d.promoted else "REJECTED"
        return lines + [f"result     already checked against this champion: {verdict} (no budget used)"]
    if d.practice:
        p = d.practice
        lines.append(f"practice   champion {p['champion']}/{p['n']}, candidate {p['candidate']}/{p['n']}")
    if d.stage == "practice":
        lines.append(f"result     REJECTED at practice; the sealed exam was not used ({d.remaining_budget} left)")
    elif d.promoted:
        lines.append(f"sealed     exam taken; {d.remaining_budget} left")
        lines.append(f"result     PROMOTED: {d.version} is the new champion")
    else:
        lines.append(f"sealed     exam taken; {d.remaining_budget} left")
        lines.append(f"result     REJECTED: {d.champion} stays the champion")
    return lines


def cmd_check(args) -> int:
    d = Gate.load(args.config).check(Path(args.candidate))
    if args.json:
        _print_json(d.to_dict())
    else:
        print("\n".join(_describe(d)))
    return EXIT_OK if d.promoted and d.stage in ("sealed", "repeat") else EXIT_REJECTED


def cmd_status(args) -> int:
    s = Gate.load(args.config).status()
    if args.json:
        _print_json(s)
        return EXIT_OK
    print(f"champion     {s['champion']}  (baseline {s['baseline']})")
    print(f"trust level  {s['trust_level']}")
    print(f"budget       {s['remaining_budget']} sealed exams left")
    if s["decisions"]:
        print("decisions")
        for d in s["decisions"]:
            how = "promoted" if d["promoted"] else f"rejected at {d['stage']}"
            print(f"  {d['version']}  vs {d['champion']}  {how}")
    return EXIT_OK


def cmd_report(args) -> int:
    gate = Gate.load(args.config)
    r = gate.report(refresh=not args.no_refresh)
    if args.json:
        _print_json(r)
        return EXIT_OK
    s = r["sealed"]
    print(f"champion     {r['champion']}  (baseline {r['baseline']})")
    print(f"sealed       {s['passes']}/{s['n']} passed ({_pct(s['pass_rate'])}; at least {_pct(s['pass_rate_lower'])} with 95% confidence)")
    print(f"trust level  {r['trust_level']}  ({', '.join(f'{lv.name}: >= {lv.min_pass_rate:.0%} on {lv.min_cases}+ cases' for lv in gate.cfg.levels)})")
    print(f"budget       {r['remaining_budget']} sealed exams left")
    if r["exams"]:
        print("exams        candidate     champion      ran       wins  losses  p        outcome")
        for e in r["exams"]:
            outcome = "promoted" if e["promoted"] else f"rejected ({e['reason']})"
            print(f"             {e['version']}  {e['champion']}  {e['ran']:>4}/{e['n']:<4} {e['b']:>4}  {e['c']:>6}  {e['p_better']:<8.2g} {outcome}")
    return EXIT_OK


def cmd_export(args) -> int:
    dest = Gate.load(args.config).export(Path(args.dest))
    print(f"copied the champion to {dest}")
    return EXIT_OK


def cmd_verify(args) -> int:
    ok = True
    for name, good, msg in Gate.load(args.config).verify():
        ok &= good
        print(f"{'ok    ' if good else 'BROKEN'}  {name}: {msg}")
    return EXIT_OK if ok else EXIT_REJECTED


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skillgate", description="A regression gate for skills that agents update themselves.")
    ap.add_argument("--version", action="version", version=f"skillgate {__version__}")
    ap.add_argument("-c", "--config", default=CONFIG_NAME, help=f"path to {CONFIG_NAME} (default: ./{CONFIG_NAME})")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help=f"write a commented {CONFIG_NAME}")
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("baseline", help="freeze the starting skill version and grade it on every case")
    p.add_argument("skill")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_baseline)

    p = sub.add_parser("check", help="gate a candidate version (exit 0 = promoted, 1 = rejected)")
    p.add_argument("candidate")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("status", help="champion, decisions, budget and trust level (no sealed numbers)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("report", help="for the human: sealed numbers behind every decision")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-refresh", action="store_true", help="do not grade the champion on newly added sealed cases")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("export", help="copy the current champion to a new directory")
    p.add_argument("dest")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("verify", help="check both ledgers and every stored version for tampering")
    p.set_defaults(fn=cmd_verify)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        return args.fn(args)
    except (ConfigError, CaseError, GateError, TamperedError, FileNotFoundError, KeyError) as e:
        print(f"skillgate: {e}", file=sys.stderr)
        return EXIT_ERROR
