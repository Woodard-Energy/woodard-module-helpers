import subprocess
from pathlib import Path


class CommandError(RuntimeError):
    """Raised when a subprocess exits non-zero."""

    def __init__(self, argv: list[str], returncode: int, stdout: str, stderr: str):
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        # Show stderr first; if empty, fall back to stdout. Trim to keep the
        # message readable but include enough context to diagnose.
        output = stderr.strip() or stdout.strip() or "(no output)"
        cmd = " ".join(argv[:4])  # e.g. "git push -u origin" — 4 tokens covers most useful commands
        super().__init__(f"{cmd} exited {returncode}: {output[:500]}")


def run(argv: list[str], cwd: str | Path | None = None, check: bool = True) -> str:
    """Run a subprocess and return stdout. Raises CommandError on non-zero.

    Single mock point for every external tool invocation (gh, git, uv, pytest).
    """
    result = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise CommandError(argv, result.returncode, result.stdout, result.stderr)
    return result.stdout
