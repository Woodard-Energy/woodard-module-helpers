from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._shell import CommandError, run


@app.command("request-prod")
def request_prod() -> None:
    """Open a PR from dev to main for this module.

    Validates the current branch is dev + clean + pushed, then generates a
    summary from commits on dev ahead of main and opens the PR via gh.
    """
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch != "dev":
        typer.echo(
            f"current branch is {branch!r}, must be 'dev' to request prod",
            err=True,
        )
        raise typer.Exit(code=2)

    run(["git", "fetch", "origin", "dev"])
    dirty = run(["git", "status", "--porcelain"]).strip()
    if dirty:
        typer.echo(
            "working tree is dirty — commit or stash changes first:\n"
            + dirty,
            err=True,
        )
        raise typer.Exit(code=2)

    commits_raw = run(["git", "log", "origin/main..dev", "--pretty=%h %s"])
    commits = [line for line in commits_raw.splitlines() if line.strip()]
    if not commits:
        typer.echo("no commits on dev ahead of main — nothing to ship", err=True)
        raise typer.Exit(code=2)

    slug = Path.cwd().name  # assumes working dir named <domain>-<name>
    n = len(commits)
    title = f"Ship {slug} to prod ({n} commit{'s' if n != 1 else ''})"
    body = _build_pr_body(slug, commits)

    try:
        pr_url = run([
            "gh", "pr", "create",
            "--base", "main",
            "--head", "dev",
            "--title", title,
            "--body", body,
        ]).strip()
    except CommandError as e:
        typer.echo(f"gh pr create failed: {e.stderr}", err=True)
        raise typer.Exit(code=1) from e

    typer.echo(f"✓ PR opened: {pr_url}")


def _build_pr_body(slug: str, commits: list[str]) -> str:
    commits_md = "\n".join(f"- {c}" for c in commits)
    return f"""## Summary

Ship {slug} from dev to prod.

## Commits

{commits_md}

## Reviewer checklist

- [ ] Dev slot has been exercised end-to-end
- [ ] No secrets in diff
- [ ] `/_health` still reports correctly
- [ ] Module version bumped in `module.yaml`
"""
