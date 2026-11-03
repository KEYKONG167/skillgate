"""Append-only JSONL ledger. Each entry carries the hash of the one before it,
so editing or deleting any past entry breaks the chain and `verify` reports it."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

GENESIS = "0" * 64


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._seq, self._last = 0, GENESIS
        for entry in self.entries():
            self._seq, self._last = entry["seq"], entry["hash"]

    def append(self, kind: str, payload: dict) -> dict:
        with self._lock:
            entry = {
                "seq": self._seq + 1,
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "kind": kind,
                "payload": payload,
                "prev": self._last,
            }
            entry["hash"] = _digest(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            self._seq, self._last = entry["seq"], entry["hash"]
            return entry

    def entries(self, kind: str | None = None) -> Iterator[dict]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if kind is None or entry["kind"] == kind:
                        yield entry

    def verify(self) -> tuple[bool, str]:
        prev, seq = GENESIS, 0
        try:
            for entry in self.entries():
                seq += 1
                if entry["seq"] != seq:
                    return False, f"sequence gap at entry {seq}"
                if entry["prev"] != prev:
                    return False, f"broken link at entry {seq}"
                if _digest(entry) != entry["hash"]:
                    return False, f"entry {seq} was modified"
                prev = entry["hash"]
        except (json.JSONDecodeError, KeyError) as e:
            return False, f"unreadable entry {seq}: {e}"
        return True, f"{seq} entries ok"
