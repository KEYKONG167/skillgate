"""Frozen skill versions. A version is named by the hash of its files, copied into
the store once, and re-hashed every time it is used, so a stored version cannot
be changed after it was checked."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

SKIP = {"__pycache__", ".git", ".pytest_cache", ".DS_Store", ".skillgate", ".skillgate-sealed"}
ID_LEN = 12


class TamperedError(RuntimeError):
    pass


def _files(root: Path):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in SKIP for part in rel.parts):
            continue
        if p.is_file():
            yield rel, p


def tree_hash(root: Path) -> str:
    root = Path(root)
    h = hashlib.sha256()
    for rel, p in _files(root):
        h.update(rel.as_posix().encode("utf-8") + b"\0")
        h.update(p.read_bytes() + b"\0")
    return h.hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    def freeze(self, src: Path) -> str:
        src = Path(src)
        if not src.is_dir():
            raise FileNotFoundError(f"skill directory not found: {src}")
        vid = tree_hash(src)[:ID_LEN]
        dest = self.root / vid
        if not dest.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=f".{vid}-", dir=self.root))
            for rel, p in _files(src):
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, tmp / rel)
            tmp.rename(dest)
        return vid

    def path(self, vid: str) -> Path:
        dest = self.root / vid
        if not dest.is_dir():
            raise KeyError(f"unknown version: {vid}")
        if tree_hash(dest)[:ID_LEN] != vid:
            raise TamperedError(f"version {vid} was modified after it was stored")
        return dest

    def ids(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")) if self.root.is_dir() else []
