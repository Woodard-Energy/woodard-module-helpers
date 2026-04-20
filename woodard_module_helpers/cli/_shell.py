import subprocess
from pathlib import Path


class CommandError(RuntimeError):
    """Raised when a subprocess exits non-zero."""

    def __init__(self, argv: list[str], returncode: int, stderr: str):
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"{' '.join(argv)} exited {returncode}: {stderr}")


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
        raise CommandError(argv, result.returncode, result.stderr)
    return result.stdout
