"""The single way this tool starts child processes.

Every child runs with stdin closed, no TTY and a hard timeout, so a tool that
waits for input can never hang an unattended run. Exit codes follow the
interface contract: a timeout or a missing executable means the environment
is not ready (3), never "the code under test failed" (1).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_ENV_NOT_READY = 3


@dataclass(frozen=True)
class RunResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run(argv: List[str], *, cwd: Path, timeout_s: int,
        env: Optional[Dict[str, str]] = None) -> RunResult:
    """Run argv without stdin and with a hard timeout.

    env, when given, replaces the environment entirely (callers decide what
    leaks into the child).
    """
    try:
        p = subprocess.run(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return RunResult(code=EXIT_ENV_NOT_READY, stdout="",
                         stderr="timeout after %ds" % timeout_s, timed_out=True)
    except FileNotFoundError:
        return RunResult(code=EXIT_ENV_NOT_READY, stdout="",
                         stderr="executable not found: %s" % argv[0])
    return RunResult(code=p.returncode, stdout=p.stdout, stderr=p.stderr)
