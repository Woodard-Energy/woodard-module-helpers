from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._output import echo, emit_error, emit_success
from woodard_module_helpers.cli._shell import CommandError, run


@app.command("request-prod")
def request_prod(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Open a PR from dev to main for this module."""
    verb = "request-prod"
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch != "dev":
        emit_error(
            verb,
            f"current branch is {branch!r}, must be 'dev'",
            json_output=json_output,
            exit_code=2,
        )

    run(["git", "fetch", "origin", "dev"])
    dirty = run(["git", "status", "--porcelain"]).strip()
    if dirty:
        emit_error(
            verb,
            f"working tree is dirty:\n{dirty}",
            json_output=json_output,
            exit_code=2,
        )

    commits_raw = run(["git", "log", "origin/main..dev", "--pretty=%h %s"])
    commits = [line for line in commits_raw.splitlines() if line.strip()]
    if not commits:
        emit_error(
            verb, "no commits on dev ahead of main",
            json_output=json_output, exit_code=2,
        )

    slug = Path.cwd().name
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
        emit_error(
            verb, f"gh pr create failed: {e.stderr}",
            json_output=json_output,
        )

    echo(f"✓ PR opened: {pr_url}", json_output=json_output)
    emit_success(
        verb,
        json_output=json_output,
        slug=slug,
        pr_url=pr_url,
        commits=commits,
    )


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
