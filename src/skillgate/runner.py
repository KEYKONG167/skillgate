"""Runs one skill version on one case through the user's command, and caches the result.

The command's last JSON line with a boolean "pass" is the result. A crash, a timeout
or a missing result line counts as a fail. Those failures are not cached, so a flaky
model API gets another try next time instead of being remembered as a real fail.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from skillgate.cases import Case, materialized
from skillgate.config import Config
from skillgate.versions import Store

MAX_DETAIL = 300


@dataclass
class Result:
    passed: bool
    error: str | None = None
    detail: str | None = None
    seconds: float = 0.0


def parse_output(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("pass"), bool):
            return obj
    return None


class Runner:
    def __init__(self, cfg: Config, store: Store, cache_dir: Path):
        self.cfg = cfg
        self.store = store
        # A different command or timeout means different results: keep them apart.
        key = hashlib.sha256(json.dumps([cfg.run, cfg.timeout]).encode("utf-8")).hexdigest()[:12]
        self.cache_dir = Path(cache_dir) / key

    def _cache_path(self, vid: str, case: Case) -> Path:
        return self.cache_dir / vid / f"{case.key}.json"

    def cached(self, vid: str, case: Case) -> Result | None:
        path = self._cache_path(vid, case)
        if not path.is_file():
            return None
        return Result(**json.loads(path.read_text(encoding="utf-8")))

    def result(self, vid: str, case: Case) -> Result:
        hit = self.cached(vid, case)
        if hit is not None:
            return hit
        res = self._execute(self.store.path(vid), case)
        if res.error is None:
            path = self._cache_path(vid, case)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(asdict(res), ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        return res

    def results(self, vid: str, cases: list[Case]) -> dict[str, Result]:
        with ThreadPoolExecutor(self.cfg.jobs) as pool:
            return dict(zip([c.id for c in cases], pool.map(lambda c: self.result(vid, c), cases)))

    def _execute(self, skill: Path, case: Case) -> Result:
        t0 = time.monotonic()
        with materialized(case) as case_path:
            subs = {"{python}": sys.executable, "{skill}": str(skill), "{case}": str(case_path), "{case_id}": case.id}
            args = []
            for arg in self.cfg.run:
                for k, v in subs.items():
                    arg = arg.replace(k, v)
                args.append(arg)
            env = {**os.environ, "SKILLGATE_SKILL": str(skill), "SKILLGATE_CASE": str(case_path), "SKILLGATE_CASE_ID": case.id}
            try:
                proc = subprocess.run(
                    args, cwd=self.cfg.root, env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=self.cfg.timeout,
                )
            except subprocess.TimeoutExpired:
                return Result(False, f"timed out after {self.cfg.timeout:g}s", seconds=time.monotonic() - t0)
            except OSError as e:
                return Result(False, f"could not start the run command: {e}", seconds=time.monotonic() - t0)
        seconds = round(time.monotonic() - t0, 3)
        out = parse_output(proc.stdout)
        if out is None:
            tail = (proc.stderr or proc.stdout or "").strip()[-MAX_DETAIL:]
            return Result(False, f"no result line (exit code {proc.returncode}): {tail}", seconds=seconds)
        detail = out.get("detail")
        return Result(out["pass"], None, str(detail)[:MAX_DETAIL] if detail is not None else None, seconds)
