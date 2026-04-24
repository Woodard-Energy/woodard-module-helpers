import json
import re
from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._domains import fetch_valid_domains
from woodard_module_helpers.cli._output import echo, emit_error, emit_success
from woodard_module_helpers.cli._shell import CommandError, run

TEMPLATE_REPO = "woodard-energy/module-template"
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


@app.command("create-module")
def create_module(
    domain: str = typer.Option(..., "--domain", "-d"),
    name: str = typer.Option(..., "--name", "-n"),
    display_name: str = typer.Option(..., "--display-name"),
    description: str = typer.Option("", "--description"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Scaffold a new platform module from the template."""
    verb = "create-module"
    valid_domains = fetch_valid_domains()

    if domain not in valid_domains:
        emit_error(
            verb,
            f"domain must be one of {valid_domains}, got {domain!r}",
            json_output=json_output,
            exit_code=2,
        )
    if not KEBAB_RE.match(name):
        emit_error(
            verb,
            f"name must be kebab-case, got {name!r}",
            json_output=json_output,
            exit_code=2,
        )

    slug = f"{domain}-{name}"
    full = f"woodard-energy/{slug}"
    echo(f"Creating {full} from template {TEMPLATE_REPO}...", json_output=json_output)

    # ── Step A: gh repo create (idempotent) ──────────────────────────────────
    _ensure_github_repo(verb, full, slug, description, display_name, json_output)

    # ── Step B: gh repo clone (idempotent) ───────────────────────────────────
    repo = Path(slug)
    _ensure_local_clone(verb, full, slug, repo, json_output)

    # ── Step C: patch placeholders (safe no-op when already patched) ─────────
    _patch_placeholders(repo, domain=domain, name=name, display_name=display_name)

    # ── Steps D-F: dev branch, commit, push (idempotent) ─────────────────────
    _ensure_dev_branch_committed_and_pushed(
        verb, repo, commit_message="Initial scaffold", json_output=json_output
    )

    echo("", json_output=json_output)
    echo(f"✓ Created {full}", json_output=json_output)
    echo(f"  Local path: {repo.resolve()}", json_output=json_output)
    echo("", json_output=json_output)
    echo("Next steps:", json_output=json_output)
    echo(f"  1. cd {slug}", json_output=json_output)
    echo(
        "  2. Open a PR to register this module in the shell manifest",
        json_output=json_output,
    )
    echo("  3. Run `woodard-cli push-dev` after your first real commit", json_output=json_output)

    emit_success(
        verb,
        json_output=json_output,
        slug=slug,
        repo=full,
        local_path=str(repo.resolve()),
        domain=domain,
        name=name,
    )


# ── Shared idempotency helpers ────────────────────────────────────────────────

def _ensure_github_repo(
    verb: str,
    full: str,
    slug: str,
    description: str,
    display_name: str,
    json_output: bool,
) -> None:
    """Create the GitHub repo from the template, or verify it already exists."""
    try:
        out = run(["gh", "repo", "view", full, "--json", "templateRepository"], check=True)
    except CommandError:
        # Repo does not exist — create it.
        try:
            run([
                "gh", "repo", "create", full,
                "--private",
                "--template", TEMPLATE_REPO,
                "--description", description or f"{display_name} module",
            ])
        except CommandError as e:
            emit_error(
                verb, f"gh repo create failed: {e}",
                json_output=json_output,
            )
        return

    # Repo exists — check that it came from our template.
    try:
        payload = json.loads(out)
        tmpl = payload.get("templateRepository") or {}
        tmpl_full_name = tmpl.get("full_name") or tmpl.get("nameWithOwner") or ""
    except (json.JSONDecodeError, AttributeError):
        tmpl_full_name = ""

    if tmpl_full_name.lower() == TEMPLATE_REPO.lower():
        echo(
            f"GitHub repo {full} already exists from template; resuming from clone step.",
            json_output=json_output,
        )
        return

    emit_error(
        verb,
        f"GitHub repo {full} exists but was not created from module-template. "
        "Refusing to modify it. If this is a stale leftover, delete it manually "
        "via `gh repo delete` or the GitHub UI.",
        json_output=json_output,
        exit_code=2,
    )


def _ensure_local_clone(
    verb: str,
    full: str,
    slug: str,
    repo: Path,
    json_output: bool,
) -> None:
    """Clone the GitHub repo locally, or verify an existing clone matches."""
    if not repo.exists():
        try:
            run(["gh", "repo", "clone", full])
        except CommandError as e:
            emit_error(
                verb,
                f"gh repo clone failed: {e}. "
                f"Note: {full} was created on GitHub — delete it manually to retry.",
                json_output=json_output,
            )
        return

    # Directory exists — must be a git repo pointing at the right remote.
    if not (repo / ".git").exists():
        emit_error(
            verb,
            f"{repo.resolve()} exists but is not a git checkout. "
            "Refusing to write into it. Move or rename the existing dir, then re-run.",
            json_output=json_output,
            exit_code=2,
        )

    try:
        origin_url = run(
            ["git", "remote", "get-url", "origin"], cwd=repo
        ).strip().lower()
    except CommandError:
        emit_error(
            verb,
            f"{repo.resolve()} is a git repo but has no 'origin' remote. "
            "Refusing to continue. Fix the remote manually, then re-run.",
            json_output=json_output,
            exit_code=2,
        )
        return  # unreachable; satisfies type checkers

    expected = f"woodard-energy/{slug}".lower()
    if expected not in origin_url:
        emit_error(
            verb,
            f"{repo.resolve()} exists but its git remote points at {origin_url!r}, "
            f"not woodard-energy/{slug}. Refusing to overwrite. "
            "Move or rename the existing dir, then re-run.",
            json_output=json_output,
            exit_code=2,
        )

    echo(
        f"Local clone already exists at {repo.resolve()}; resuming.",
        json_output=json_output,
    )


def _ensure_dev_branch_committed_and_pushed(
    verb: str,
    repo: Path,
    commit_message: str,
    json_output: bool,
) -> None:
    """Create/verify the dev branch, commit any pending changes, push to origin."""
    # ── Step D: dev branch ───────────────────────────────────────────────────
    try:
        run(["git", "rev-parse", "--verify", "dev"], cwd=repo, check=True)
        dev_exists = True
    except CommandError:
        dev_exists = False

    if not dev_exists:
        try:
            run(["git", "checkout", "-b", "dev"], cwd=repo)
        except CommandError as e:
            emit_error(verb, f"git checkout -b dev failed: {e}", json_output=json_output)
    else:
        # Dev exists — check if it has extra commits beyond main.
        try:
            ahead_raw = run(
                ["git", "rev-list", "--count", "origin/main..dev"], cwd=repo
            ).strip()
            ahead = int(ahead_raw) if ahead_raw.isdigit() else 0
        except CommandError:
            ahead = 0

        if ahead > 0:
            emit_error(
                verb,
                "dev branch already has commits beyond main. Resume manually if these "
                "are intentional, or delete the dev branch (git branch -D dev) and "
                "re-run if it's stale.",
                json_output=json_output,
                exit_code=2,
            )

        try:
            run(["git", "checkout", "dev"], cwd=repo)
        except CommandError as e:
            emit_error(verb, f"git checkout dev failed: {e}", json_output=json_output)

    # ── Step E: add + commit ──────────────────────────────────────────────────
    try:
        run(["git", "add", "-A"], cwd=repo)
        status = run(["git", "status", "--porcelain"], cwd=repo).strip()
    except CommandError as e:
        emit_error(verb, f"git add/status failed: {e}", json_output=json_output)
        return

    if status:
        try:
            run(["git", "commit", "-m", commit_message], cwd=repo)
        except CommandError as e:
            emit_error(verb, f"git commit failed: {e}", json_output=json_output)
    else:
        echo("Working tree clean; skipping commit.", json_output=json_output)

    # ── Step F: push ─────────────────────────────────────────────────────────
    try:
        run(["git", "ls-remote", "--exit-code", "--heads", "origin", "dev"], cwd=repo, check=True)
        remote_dev_exists = True
    except CommandError:
        remote_dev_exists = False

    if remote_dev_exists:
        # Compare local dev tip with origin/dev.
        try:
            local_sha = run(["git", "rev-parse", "dev"], cwd=repo).strip()
            remote_sha = run(["git", "rev-parse", "origin/dev"], cwd=repo).strip()
        except CommandError:
            local_sha = remote_sha = None

        if local_sha and remote_sha:
            if local_sha == remote_sha:
                echo("origin/dev already up to date; skipping push.", json_output=json_output)
                return

            # Check whether local is ahead or diverged.
            try:
                behind_raw = run(
                    ["git", "rev-list", "--count", "dev..origin/dev"], cwd=repo
                ).strip()
                behind = int(behind_raw) if behind_raw.isdigit() else 0
            except CommandError:
                behind = 0

            if behind > 0:
                emit_error(
                    verb,
                    "Local dev branch diverges from origin/dev. "
                    "Resolve manually before re-running.",
                    json_output=json_output,
                    exit_code=2,
                )

    try:
        run(["git", "push", "-u", "origin", "dev"], cwd=repo)
    except CommandError as e:
        emit_error(verb, f"git push failed: {e}", json_output=json_output)


def _patch_placeholders(
    repo: Path, *, domain: str, name: str, display_name: str
) -> None:
    slug = f"{domain}-{name}"

    mod_yaml = repo / "module.yaml"
    if mod_yaml.exists():
        text = mod_yaml.read_text(encoding="utf-8")
        text = text.replace(
            "display_name: REPLACE_ME", f"display_name: {display_name}"
        )
        text = text.replace("name: REPLACE_ME", f"name: {name}")
        text = text.replace("domain: REPLACE_ME", f"domain: {domain}")
        mod_yaml.write_text(text, encoding="utf-8")

    pyproj = repo / "pyproject.toml"
    if pyproj.exists():
        text = pyproj.read_text(encoding="utf-8")
        text = text.replace('name = "REPLACE_ME"', f'name = "{slug}"')
        pyproj.write_text(text, encoding="utf-8")

    claude = repo / ".claude" / "CLAUDE.md"
    if claude.exists():
        text = claude.read_text(encoding="utf-8")
        text = text.replace("# Module: REPLACE_ME", f"# Module: {display_name}")
        text = text.replace("**Domain:** `REPLACE_ME`", f"**Domain:** `{domain}`")
        claude.write_text(text, encoding="utf-8")

    readme = repo / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        text = text.replace("# REPLACE_ME", f"# {display_name}", 1)
        readme.write_text(text, encoding="utf-8")
