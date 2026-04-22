import json as _json
from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._output import echo, emit_error, emit_success
from woodard_module_helpers.cli._shell import CommandError, run

# Infrastructure repos that aren't modules — never offer these to clone via this verb.
EXCLUDE_REPOS = frozenset({
    "intelligence-platform",
    "module-helpers",
    "module-template",
    "claude-platform-skills",
})


@app.command("clone-module")
def clone_module(
    slug: str = typer.Option(
        None, "--slug", "-s",
        help="Module slug (e.g. 'reservoir-model-optimizer'). Omit for interactive list.",
    ),
    dest: str = typer.Option(
        ".", "--dest", "-d",
        help="Parent directory to clone into. Default: cwd.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Clone an existing platform module onto your machine.

    Lists accessible woodard-energy module repos (respecting your gh auth).
    Clones the chosen repo, switches to the `dev` branch if it exists, and
    prints next-step hints.
    """
    verb = "clone-module"

    # Get repos the user can see
    try:
        result = run([
            "gh", "repo", "list", "woodard-energy",
            "--json", "name,description,visibility",
            "--limit", "100",
        ])
    except CommandError as e:
        emit_error(verb, f"gh repo list failed: {e.stderr}", json_output=json_output)

    try:
        repos = _json.loads(result)
    except _json.JSONDecodeError as e:
        emit_error(verb, f"could not parse gh repo list output: {e}", json_output=json_output)

    # Filter to likely-module repos (exclude infra)
    module_repos = [r for r in repos if r["name"] not in EXCLUDE_REPOS]
    if not module_repos:
        emit_error(
            verb,
            "No accessible module repos found in woodard-energy. "
            "Check `gh auth status` and repo access.",
            json_output=json_output,
        )

    module_names = {r["name"] for r in module_repos}

    # Interactive selection if slug not provided
    if not slug:
        echo("Accessible modules:", json_output=json_output)
        for i, r in enumerate(module_repos, 1):
            desc = r.get("description") or "(no description)"
            echo(f"  {i}. {r['name']} — {desc}", json_output=json_output)
        choice = typer.prompt("Clone which? (slug or number)")
        choice = choice.strip()
        # Allow either a number or the slug itself
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(module_repos):
                slug = module_repos[idx]["name"]
            else:
                emit_error(
                    verb, f"selection {choice} out of range", json_output=json_output, exit_code=2
                )
        else:
            slug = choice

    # Validate
    if slug not in module_names:
        emit_error(
            verb,
            f"{slug!r} is not an accessible module repo. "
            f"Run without --slug to see the list.",
            json_output=json_output,
            exit_code=2,
        )

    full = f"woodard-energy/{slug}"
    dest_path = Path(dest).resolve()
    target = dest_path / slug

    if target.exists():
        emit_error(
            verb,
            f"Target directory already exists: {target}. "
            f"Remove it or choose a different --dest.",
            json_output=json_output,
            exit_code=2,
        )

    echo(f"Cloning {full} into {target}...", json_output=json_output)
    try:
        run(["gh", "repo", "clone", full, str(target)])
    except CommandError as e:
        emit_error(verb, f"gh repo clone failed: {e.stderr}", json_output=json_output)

    # Check for dev branch; if present, switch to it
    on_dev = False
    try:
        branches = run(["git", "branch", "-r"], cwd=target)
        if "origin/dev" in branches:
            run(["git", "checkout", "dev"], cwd=target)
            on_dev = True
    except CommandError:
        # Non-fatal — just didn't switch. User still has main.
        pass

    echo("", json_output=json_output)
    echo(f"Cloned {full}", json_output=json_output)
    echo(f"  Local path: {target}", json_output=json_output)
    if on_dev:
        echo("  Branch: dev (switched from main)", json_output=json_output)
    else:
        echo(
            "  Branch: main (no origin/dev found; create one with `git checkout -b dev`)",
            json_output=json_output,
        )
    echo("", json_output=json_output)
    echo("Next steps:", json_output=json_output)
    echo(f"  1. cd {target}", json_output=json_output)
    echo("  2. Run `uv sync` to install deps", json_output=json_output)
    echo(
        "  3. Iterate, then `woodard-cli push-dev` to deploy your changes",
        json_output=json_output,
    )

    emit_success(
        verb,
        json_output=json_output,
        slug=slug,
        repo=full,
        local_path=str(target),
        branch="dev" if on_dev else "main",
    )
