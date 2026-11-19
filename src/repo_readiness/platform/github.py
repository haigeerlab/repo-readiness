"""Read-only GitHub access through the `gh` CLI, with record / replay for tests.

Every request is `gh api -i --method GET <path>`; nothing else is ever run.
Paths are validated before anything executes, so a ruler cannot smuggle in
flags, other methods or other hosts.

Responses are classified so probes can tell "the repository lacks this"
apart from "we could not look":

    ok, not_found, forbidden                      -> a real answer about the repo
    unauthenticated, network, rate_limited,
    server_error, gh_missing                      -> env_error: environment not ready

(Observed with gh 2.98.0: stdout is a status line, headers, a blank line and
the body; exit 0 on 2xx, 1 on HTTP errors, 4 when not logged in.)
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from repo_readiness.probes.runtime import HarnessError
from repo_readiness.proc import run

__all__ = ["GhResponse", "GitHub", "LiveTransport", "RecordingTransport", "ReplayMissing", "ReplayTransport"]

_PATH_OK = re.compile(r"[A-Za-z0-9_][A-Za-z0-9/_.,%=&?+~-]*\Z")
_STATUS = re.compile(r"HTTP/\S+ (\d{3})")
ENV_STATUSES = {"unauthenticated", "network", "rate_limited", "server_error", "gh_missing"}


@dataclass
class GhResponse:
    status: str
    http_status: Optional[int] = None
    data: Any = None
    message: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def env_error(self) -> bool:
        return self.status in ENV_STATUSES

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _check_path(path: str) -> None:
    if not isinstance(path, str) or not _PATH_OK.match(path) or ".." in path.split("/"):
        raise ValueError("refusing GitHub API path %r (only plain read-only REST paths are allowed)" % (path,))


class LiveTransport:
    def __init__(self, gh: str = "gh", timeout_s: int = 30):
        self.gh = gh
        self.timeout_s = timeout_s

    def fetch(self, path: str) -> GhResponse:
        r = run([self.gh, "api", "-i", "--method", "GET", path], cwd=Path("/"), timeout_s=self.timeout_s)
        if r.timed_out:
            return GhResponse("network", message="gh api timed out after %ds" % self.timeout_s)
        if r.code == 3 and r.stderr.startswith("executable not found"):
            return GhResponse("gh_missing", message="GitHub CLI (gh) is not installed or not on PATH")
        if r.code == 4:
            return GhResponse("unauthenticated", message=r.stderr.strip() or "gh is not logged in (run: gh auth login)")
        text = r.stdout.replace("\r\n", "\n")
        head, _, body = text.partition("\n\n")
        lines = head.split("\n")
        m = _STATUS.match(lines[0]) if lines else None
        if not m:
            return GhResponse("network", message=(r.stderr.strip() or "no HTTP response from gh")[:500])
        code = int(m.group(1))
        headers = {}
        for line in lines[1:]:
            k, sep, v = line.partition(":")
            if sep:
                headers[k.strip().lower()] = v.strip()
        try:
            data = json.loads(body) if body.strip() else None
        except ValueError:
            data = None
        msg = data.get("message", "") if isinstance(data, dict) else ""
        if 200 <= code < 300:
            status = "ok"
        elif code == 404:
            status = "not_found"
        elif code == 401:
            status = "unauthenticated"
        elif code in (403, 429) and (headers.get("x-ratelimit-remaining") == "0" or "rate limit" in msg.lower()):
            status = "rate_limited"
        elif code == 403:
            status = "forbidden"
        elif code >= 500:
            status = "server_error"
        else:
            status = "forbidden" if code == 422 else "server_error"
        return GhResponse(status, http_status=code, data=data, message=msg or r.stderr.strip()[:500], headers=headers)


class ReplayMissing(HarnessError):
    """A test asked for a GitHub path that was never recorded."""


def _record_name(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16] + ".json"


class RecordingTransport:
    """Pass requests to another transport and save each response under dir_."""

    def __init__(self, inner: Any, dir_: Path):
        self.inner = inner
        self.dir = Path(dir_)

    def fetch(self, path: str) -> GhResponse:
        resp = self.inner.fetch(path)
        self.dir.mkdir(parents=True, exist_ok=True)
        rec = dict(asdict(resp), path=path)
        rec["headers"] = {k: v for k, v in resp.headers.items() if k.startswith("x-ratelimit") or k == "content-type"}
        (self.dir / _record_name(path)).write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
        return resp


class ReplayTransport:
    """Answer only from recordings; an unrecorded path is a test bug, not a network error."""

    def __init__(self, dir_: Path):
        self.dir = Path(dir_)

    def fetch(self, path: str) -> GhResponse:
        f = self.dir / _record_name(path)
        if not f.is_file():
            raise ReplayMissing("no recording for %r in %s" % (path, self.dir))
        rec = json.loads(f.read_text(encoding="utf-8"))
        return GhResponse(rec["status"], rec.get("http_status"), rec.get("data"), rec.get("message", ""),
                          rec.get("headers", {}))


class GitHub:
    def __init__(self, transport: Any):
        self.transport = transport
        self._cache = {}  # type: Dict[str, GhResponse]

    def get(self, path: str) -> GhResponse:
        _check_path(path)
        if path not in self._cache:
            self._cache[path] = self.transport.fetch(path)
        return self._cache[path]
