import shutil
from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._output import echo, emit_error, emit_success
from woodard_module_helpers.cli._shell import CommandError, run
from woodard_module_helpers.cli.create_module import (
    KEBAB_RE,
    TEMPLATE_REPO,
    VALID_DOMAINS,
    _patch_placeholders,
)

EXCLUDE = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"}
REQUIRED = ("app",)


@app.command("convert-to-platform")
def convert_to_platform(
    source: str = typer.Option(..., "--source", "-s"),
    domain: str = typer.Option(..., "--domain", "-d"),
    name: str = typer.Option(..., "--name", "-n"),
    display_name: str = typer.Option(..., "--display-name"),
    description: str = typer.Option("", "--description"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Promote an existing personal-use project into a platform module."""
    verb = "convert-to-platform"

    if domain not in VALID_DOMAINS:
        emit_error(
            verb, f"domain must be one of {VALID_DOMAINS}",
            json_output=json_output, exit_code=2,
        )
    if not KEBAB_RE.match(name):
        emit_error(
            verb, "name must be kebab-case",
            json_output=json_output, exit_code=2,
        )

    src = Path(source).resolve()
    missing = [r for r in REQUIRED if not (src / r).exists()]
    if missing:
        emit_error(
            verb,
            f"source missing required dirs: {missing} (expected at least 'app/')",
            json_output=json_output, exit_code=2,
        )

    slug = f"{domain}-{name}"
    full = f"woodard-energy/{slug}"
    echo(
        f"Creating {full} from template {TEMPLATE_REPO}...",
        json_output=json_output,
    )

    try:
        run([
            "gh", "repo", "create", full,
            "--private",
            "--template", TEMPLATE_REPO,
            "--description",
            description or f"{display_name} (converted from {src.name})",
        ])
    except CommandError as e:
        emit_error(
            verb, f"gh repo create failed: {e.stderr}",
            json_output=json_output,
        )

    try:
        run(["gh", "repo", "clone", full])
    except CommandError as e:
        emit_error(
            verb,
            f"gh repo clone failed: {e.stderr}. "
            f"Note: {full} was created on GitHub — delete it manually to retry.",
            json_output=json_output,
        )

    dest = Path(slug)
    _copy_source_into_dest(src, dest)
    _patch_placeholders(
        dest, domain=domain, name=name, display_name=display_name
    )

    try:
        run(["git", "checkout", "-B", "dev"], cwd=dest)
        run(["git", "add", "-A"], cwd=dest)
        run(
            ["git", "commit", "-m", f"Convert {src.name} to platform module"],
            cwd=dest,
        )
        run(["git", "push", "-u", "origin", "dev"], cwd=dest)
    except CommandError as e:
        emit_error(verb, f"git failed: {e.stderr}", json_output=json_output)

    echo("", json_output=json_output)
    echo(f"✓ Converted {src} → {full}", json_output=json_output)
    echo(f"  Local path: {dest.resolve()}", json_output=json_output)

    emit_success(
        verb,
        json_output=json_output,
        slug=slug,
        repo=full,
        source=str(src),
        local_path=str(dest.resolve()),
    )


def _copy_source_into_dest(src: Path, dest: Path) -> None:
    for item in src.iterdir():
        if item.name in EXCLUDE:
            continue
        target = dest / item.name
        if target.exists() and target.is_file():
            continue
        if item.is_dir():
            shutil.copytree(
                item, target,
                ignore=shutil.ignore_patterns(*EXCLUDE),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(item, target)
