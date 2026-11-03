"""Test cases. A case pool is either a directory with one sub-directory per case,
or a JSONL file with one JSON object per line (the object's "id" names the case,
otherwise its line number does). skillgate never looks inside a case: it hands
the case to your run command, which decides pass or fail."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from skillgate.versions import tree_hash


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Case:
    id: str
    digest: str  # changes whenever the case content changes, so stale results are never reused
    source: Path
    data: str | None = None  # canonical JSON for JSONL cases; None for directory cases

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.id}\0{self.digest}".encode("utf-8")).hexdigest()[:20]


def load_cases(path: Path) -> list[Case]:
    path = Path(path)
    if path.is_dir():
        cases = [
            Case(p.name, tree_hash(p)[:16], p)
            for p in sorted(path.iterdir())
            if p.is_dir() and not p.name.startswith(".")
        ]
    elif path.is_file() and path.suffix == ".jsonl":
        cases = []
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise CaseError(f"{path}:{n}: not valid JSON ({e.msg})") from None
            if not isinstance(obj, dict):
                raise CaseError(f"{path}:{n}: each line must be a JSON object")
            data = json.dumps(obj, ensure_ascii=False, sort_keys=True)
            cid = str(obj.get("id", f"line-{n:05d}"))
            cases.append(Case(cid, hashlib.sha256(data.encode("utf-8")).hexdigest()[:16], path, data))
    elif path.exists():
        raise CaseError(f"{path}: case pool must be a directory or a .jsonl file")
    else:
        raise CaseError(f"case pool not found: {path}")
    seen: set[str] = set()
    for c in cases:
        if c.id in seen:
            raise CaseError(f"{path}: duplicate case id {c.id!r}")
        seen.add(c.id)
    return cases


@contextmanager
def materialized(case: Case) -> Iterator[Path]:
    """The path handed to the run command: the case directory, or a temporary
    case.json holding one JSONL line."""
    if case.data is None:
        yield case.source
        return
    tmp = Path(tempfile.mkdtemp(prefix="skillgate-case-"))
    try:
        path = tmp / "case.json"
        path.write_text(case.data, encoding="utf-8")
        yield path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
