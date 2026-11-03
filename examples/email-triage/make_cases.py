"""Regenerates cases/practice.jsonl and sealed/cases.jsonl (deterministic).

Each case is a short support email and the team it should go to. Every
category has five ways of saying the same thing; the starting rules only
know two of them, so there is real room to improve.
"""

import json
import random
from pathlib import Path

PHRASES = {
    "billing": ["invoice", "refund", "charged twice", "payment failed", "receipt"],
    "bug": ["error message", "app crashes", "page freezes", "button is broken", "won't load"],
    "account": ["reset my password", "can't log in", "sign in", "change my username", "two-factor code"],
    "other": ["feature idea", "pricing for teams", "partnership", "great product", "office hours"],
}
OPENERS = ["Hi team,", "Hello,", "Hey there,", "Good morning,"]
BODIES = ["I have a question about the {p}.", "Quick note: {p} since yesterday.", "Could you look into the {p}?", "Writing about {p}."]
CLOSERS = ["Please help.", "Please advise.", "Thanks a lot.", "Thank you!", "Please get back to me soon.", "Cheers."]


def make(n: int, rng: random.Random, prefix: str) -> list[dict]:
    cases = []
    for i in range(n):
        label = rng.choice(sorted(PHRASES))
        text = " ".join([rng.choice(OPENERS), rng.choice(BODIES).format(p=rng.choice(PHRASES[label])), rng.choice(CLOSERS)])
        cases.append({"id": f"{prefix}-{i:03d}", "text": text, "expected": label})
    return cases


def write(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")


if __name__ == "__main__":
    here = Path(__file__).parent
    write(here / "cases" / "practice.jsonl", make(60, random.Random(1), "p"))
    write(here / "sealed" / "cases.jsonl", make(240, random.Random(2), "s"))
