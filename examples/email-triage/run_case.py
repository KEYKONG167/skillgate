"""Runs one version of the triage skill on one case and prints {"pass": ...}.

This file is the trusted part: it knows the expected answer. The skill under
test (rules.json) only ever sees the email text.
"""

import argparse
import json
from pathlib import Path


def triage(rules: dict, text: str) -> str:
    text = text.lower()
    for label, words in rules["rules"]:
        if any(w in text for w in words):
            return label
    return rules["default"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--case", required=True)
    args = ap.parse_args()
    rules = json.loads((Path(args.skill) / "rules.json").read_text(encoding="utf-8"))
    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    got = triage(rules, case["text"])
    print(json.dumps({"pass": got == case["expected"], "detail": f"sent to {got}, expected {case['expected']}"}))
