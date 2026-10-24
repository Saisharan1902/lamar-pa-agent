"""Local submission ledger: the agent's guard against double-submitting.

Before the final submit click the record is marked 'submitting'. When the portal
confirms an outcome the entry becomes 'done' with the result. On the next run:
  * done        -> return the stored result, do not touch the portal
  * submitting  -> a previous run died after clicking submit; we cannot know if the
                   request exists, so escalate instead of risking a duplicate.
"""
import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path


def record_key(portal_origin, record):
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((portal_origin + "\n" + canonical).encode()).hexdigest()[:20]


class Ledger:
    def __init__(self, state_dir):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "ledger.json"

    @contextmanager
    def _locked(self):
        with open(self.dir / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text()) if self.path.exists() else {}
            yield data
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            os.replace(tmp, self.path)

    def get(self, key):
        with self._locked() as d:
            return d.get(key)

    def claim(self, key):
        """Atomically reserve the side effect; only one concurrent run can win."""
        with self._locked() as d:
            if key in d:
                return False
            d[key] = {"state": "submitting"}
            return True

    def mark_submitting(self, key):
        with self._locked() as d:
            d[key] = {"state": "submitting"}

    def mark_done(self, key, result):
        with self._locked() as d:
            d[key] = {"state": "done", "result": result}

    def clear(self, key):
        with self._locked() as d:
            d.pop(key, None)
