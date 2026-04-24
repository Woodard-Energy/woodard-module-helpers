"""Tests for the create-module verb.

Covers both the original happy-path behaviour and the new idempotency/
safe-resume logic added in v0.2.1.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._shell import CommandError


@pytest.fixture(autouse=True)
def _mock_domains(mocker):
    mocker.patch(
        "woodard_module_helpers.cli.create_module.fetch_valid_domains",
        return_value=("drilling", "geology", "land", "midstream", "reservoir"),
    )


@pytest.fixture
def _fake_shell(mocker):
    """Mock _shell.run so no real subprocess calls happen."""
    return mocker.patch("woodard_module_helpers.cli.create_module.run", return_value="")


# ── Validation ────────────────────────────────────────────────────────────────

def test_rejects_invalid_domain(_fake_shell):
    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "made-up", "--name", "foo", "--display-name", "Foo"
    ])
    assert r.exit_code != 0
    assert (
        "domain must be one of" in r.stdout.lower()
        or "domain must be one of" in r.stderr.lower()
    )
    _fake_shell.assert_not_called()


def test_rejects_non_kebab_name(_fake_shell):
    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "Bad_Name", "--display-name", "X"
    ])
    assert r.exit_code != 0
    _fake_shell.assert_not_called()


# ── Shared smart_run factory ──────────────────────────────────────────────────

def _base_smart_run(*, repo_view_raises=True, dev_exists=False, dev_ahead=0,
                    remote_dev_sha=None, local_dev_sha=None, origin_dev_sha=None,
                    status_output="M module.yaml\n"):
    """
    Build a smart_run function for create-module tests.

    argv dispatch uses argv[0]+argv[1] for gh subcommands and argv[1] for git
    subcommands (subcommand-level matching, not positional-slice).
    """
    def smart_run(argv, **kw):
        # ── gh ──────────────────────────────────────────────────────────────
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            if repo_view_raises:
                raise CommandError(argv, 1, "", "repository not found")
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        # gh api repos/.../commits — template already populated
        if argv[0] == "gh" and argv[1] == "api" and len(argv) > 2 and "commits" in argv[2]:
            return "1"
        if argv[0] == "gh":
            return ""
        # ── git ─────────────────────────────────────────────────────────────
        if argv[1] == "rev-parse" and "--verify" in argv:
            if dev_exists:
                return "abc1234\n"
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv:
            # Distinguish the clone commit-count check (HEAD) from the
            # dev-ahead check (origin/main..dev).
            if "HEAD" in argv:
                return "3\n"  # clone has commits — not stuck in race loop
            return f"{dev_ahead}\n"
        if argv[1] == "status":
            return status_output
        if argv[1] == "ls-remote":
            if remote_dev_sha:
                return f"{remote_dev_sha}\trefs/heads/dev\n"
            raise CommandError(argv, 2, "", "")
        if argv[1] == "rev-parse" and argv[2] == "dev":
            return f"{local_dev_sha or 'aabbccdd'}\n"
        if argv[1] == "rev-parse" and argv[2] == "origin/dev":
            return f"{origin_dev_sha or 'aabbccdd'}\n"
        return ""
    return smart_run


# ── Happy path ────────────────────────────────────────────────────────────────

def test_happy_path_runs_expected_commands(tmp_path, monkeypatch, mocker):
    """Happy path: repo doesn't exist → create → clone → dev branch → push."""
    monkeypatch.chdir(tmp_path)

    run_mock = mocker.patch(
        "woodard_module_helpers.cli.create_module.run",
        side_effect=_base_smart_run(repo_view_raises=True, status_output="M module.yaml\n"),
    )

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module",
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout

    argvs = [c.args[0] for c in run_mock.call_args_list]
    # gh repo create from template, private
    assert any(
        a[:3] == ["gh", "repo", "create"]
        and "woodard-energy/geology-well-lookup" in a
        and "--private" in a
        and "--template" in a
        for a in argvs
    ), argvs
    # gh repo clone
    assert any(
        a[:3] == ["gh", "repo", "clone"]
        and "woodard-energy/geology-well-lookup" in a
        for a in argvs
    ), argvs
    # git commit "Initial scaffold"
    assert any(
        a[0] == "git" and a[1] == "commit" and "Initial scaffold" in " ".join(a)
        for a in argvs
    ), argvs
    # git push to dev
    assert any(
        a[0] == "git" and a[1] == "push" and "dev" in a for a in argvs
    ), argvs


def test_happy_path_runs_expected_commands_with_view_miss(tmp_path, monkeypatch, mocker):
    """Full happy path: gh repo view raises (repo doesn't exist) → create → clone → push."""
    monkeypatch.chdir(tmp_path)
    mocker.patch(
        "woodard_module_helpers.cli.create_module.run",
        side_effect=_base_smart_run(repo_view_raises=True, status_output="M module.yaml\n"),
    )

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module",
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout


def test_patches_module_yaml_with_inputs(tmp_path, monkeypatch, mocker):
    """Simulate a cloned repo with template placeholders; verify patching.

    Fixture intentionally puts `display_name:` before `name:` so the
    substring-collision path is exercised. Without the display_name-first
    ordering in _patch_placeholders, `str.replace("name: REPLACE_ME", ...)`
    would corrupt the `display_name: REPLACE_ME` line.
    """
    monkeypatch.chdir(tmp_path)
    repo_dir = tmp_path / "geology-well-lookup"
    repo_dir.mkdir()
    (repo_dir / "module.yaml").write_text(
        "display_name: REPLACE_ME\nname: REPLACE_ME\ndomain: REPLACE_ME\n"
    )
    (repo_dir / "pyproject.toml").write_text(
        '[project]\nname = "REPLACE_ME"\n'
    )
    (repo_dir / ".claude").mkdir()
    (repo_dir / ".claude" / "CLAUDE.md").write_text(
        "# Module: REPLACE_ME\n\n**Domain:** `REPLACE_ME`\n"
    )
    (repo_dir / "README.md").write_text("# REPLACE_ME\n\nSome content.\n", encoding="utf-8")
    # Also create .git/ so idempotency check passes when clone is skipped.
    git_dir = repo_dir / ".git"
    git_dir.mkdir()
    fetch = "+refs/heads/*:refs/remotes/origin/*"
    (git_dir / "config").write_text(
        f"[core]\n\trepositoryformatversion = 0\n"
        f"[remote \"origin\"]\n\turl = https://github.com/woodard-energy/geology-well-lookup.git"
        f"\n\tfetch = {fetch}\n"
    )
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

    def smart_run(argv, **kw):
        # Repo already exists from template → skip create
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh":
            return ""
        # git remote get-url origin → matching remote
        if argv[1] == "remote" and argv[2] == "get-url":
            return "https://github.com/woodard-energy/geology-well-lookup.git\n"
        # dev branch doesn't exist → create it
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"  # clone has commits — not stuck in race loop
        if argv[1] == "status":
            return "M module.yaml\n"  # dirty → commit
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module",
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout

    mod_yaml = (repo_dir / "module.yaml").read_text()
    # Must have the correct values AND display_name line must not be corrupted.
    assert "display_name: Well Lookup" in mod_yaml
    assert "name: well-lookup" in mod_yaml
    assert "domain: geology" in mod_yaml
    # Regression guard: the collision bug would produce "diswell-lookupay_name: ..."
    assert "diswell-lookupay_name" not in mod_yaml

    pyproj = (repo_dir / "pyproject.toml").read_text()
    assert 'name = "geology-well-lookup"' in pyproj
    claude = (repo_dir / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "# Module: Well Lookup" in claude
    assert "**Domain:** `geology`" in claude
    assert "REPLACE_ME" not in claude

    readme = (repo_dir / "README.md").read_text(encoding="utf-8")
    assert "# Well Lookup" in readme
    assert "REPLACE_ME" not in readme


# ── Idempotency: Step A (GitHub repo) ────────────────────────────────────────

def test_create_module_resumes_when_repo_exists_from_template(
    tmp_path, monkeypatch, mocker
):
    """gh repo view returns existing template repo → skip create, proceed to clone."""
    monkeypatch.chdir(tmp_path)

    created = {"repo": False}

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {
                    "full_name": "Woodard-Energy/module-template"
                }
            })
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "create":
            created["repo"] = True
            return ""
        if argv[0] == "gh":
            return ""
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"  # clone has commits — not stuck in race loop
        if argv[1] == "status":
            return "M module.yaml\n"
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert not created["repo"], "gh repo create should have been skipped"
    assert "resuming" in r.stdout.lower() or "already exists" in r.stdout.lower()


def test_create_module_refuses_to_overwrite_non_template_repo(
    tmp_path, monkeypatch, mocker
):
    """gh repo view returns existing repo NOT from our template → exit 2 + clear error."""
    monkeypatch.chdir(tmp_path)

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            # Repo exists but template is null / different
            return json.dumps({"templateRepository": None})
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 2
    combined = r.stdout + (r.stderr or "")
    assert "not created from module-template" in combined.lower() or \
           "refusing" in combined.lower()


# ── Idempotency: Step B (local clone) ────────────────────────────────────────

def _make_git_dir(path: Path, remote_url: str) -> None:
    """Create a minimal .git/ structure with a configured origin remote."""
    git = path / ".git"
    git.mkdir(parents=True)
    fetch = "+refs/heads/*:refs/remotes/origin/*"
    (git / "config").write_text(
        f"[core]\n\trepositoryformatversion = 0\n"
        f"[remote \"origin\"]\n\turl = {remote_url}\n\tfetch = {fetch}\n"
    )
    (git / "HEAD").write_text("ref: refs/heads/main\n")


def test_create_module_resumes_when_local_clone_exists_with_correct_remote(
    tmp_path, monkeypatch, mocker
):
    """Local .git/ exists with matching remote → clone step skipped, resuming."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")

    cloned = {"n": 0}

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "clone":
            cloned["n"] += 1
            return ""
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"https://github.com/woodard-energy/{slug}.git\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"  # clone has commits — not stuck in race loop
        if argv[1] == "status":
            return ""  # nothing to commit
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert cloned["n"] == 0, "gh repo clone should have been skipped"
    assert "resuming" in r.stdout.lower()


def test_create_module_refuses_to_overwrite_local_dir_with_different_remote(
    tmp_path, monkeypatch, mocker
):
    """Local .git/ points at a different remote → stop with clear error."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, "https://github.com/someone-else/totally-different.git")

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[1] == "remote" and argv[2] == "get-url":
            return "https://github.com/someone-else/totally-different.git\n"
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "refusing" in combined.lower()
    assert "someone-else" in combined.lower() or "totally-different" in combined.lower()


def test_create_module_refuses_local_dir_that_is_not_git(
    tmp_path, monkeypatch, mocker
):
    """Existing dir without .git/ → stop, don't write into it."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    # No .git/ — just a plain directory.

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "not a git checkout" in combined.lower() or "refusing" in combined.lower()


# ── Idempotency: Step D (dev branch) ─────────────────────────────────────────

def test_create_module_stops_when_dev_has_extra_commits(
    tmp_path, monkeypatch, mocker
):
    """dev branch exists with commits ahead of main → stop with clear error."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"https://github.com/woodard-energy/{slug}.git\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            return "abc1234\n"  # dev exists
        if argv[1] == "rev-list" and "--count" in argv:
            return "3\n"  # 3 commits ahead
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "dev branch" in combined.lower()
    assert "commits" in combined.lower()


# ── Idempotency: Step E (commit) ─────────────────────────────────────────────

def test_create_module_skips_commit_when_nothing_to_commit(
    tmp_path, monkeypatch, mocker
):
    """Placeholders already patched, working tree clean → no commit, no error."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")

    committed = {"n": 0}

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"https://github.com/woodard-energy/{slug}.git\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")  # no dev branch yet
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"  # clone has commits — not stuck in race loop
        if argv[1] == "status":
            return ""  # clean tree
        if argv[1] == "commit":
            committed["n"] += 1
            return ""
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert committed["n"] == 0, "git commit should have been skipped"
    assert "clean" in r.stdout.lower() or "skipping commit" in r.stdout.lower()


# ── Idempotency: Step F (push) ────────────────────────────────────────────────

def test_create_module_skips_push_when_origin_dev_already_in_sync(
    tmp_path, monkeypatch, mocker
):
    """origin/dev exists and is identical to local dev → skip push."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")

    pushed = {"n": 0}
    SAME_SHA = "deadbeef" * 5

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"https://github.com/woodard-energy/{slug}.git\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"  # clone has commits — not stuck in race loop
        if argv[1] == "status":
            return ""  # clean
        if argv[1] == "ls-remote":
            # origin has dev
            return f"{SAME_SHA}\trefs/heads/dev\n"
        if argv[1] == "rev-parse" and len(argv) > 2 and argv[2] in ("dev", "origin/dev"):
            return f"{SAME_SHA}\n"
        if argv[1] == "push":
            pushed["n"] += 1
            return ""
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert pushed["n"] == 0, "git push should have been skipped"
    assert "up to date" in r.stdout.lower() or "skipping push" in r.stdout.lower()


def test_create_module_stops_when_local_dev_diverges_from_origin(
    tmp_path, monkeypatch, mocker
):
    """Local dev diverges from origin/dev (local is behind) → stop with error."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"https://github.com/woodard-energy/{slug}.git\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "status":
            return ""  # clean
        if argv[1] == "ls-remote":
            return "aabbccdd\trefs/heads/dev\n"
        if argv[1] == "rev-parse" and len(argv) > 2 and argv[2] == "dev":
            return "11223344\n"  # different from remote
        if argv[1] == "rev-parse" and len(argv) > 2 and argv[2] == "origin/dev":
            return "aabbccdd\n"
        if argv[1] == "rev-list" and "--count" in argv:
            return "2\n"  # local is behind remote (behind > 0 → diverged)
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "diverges" in combined.lower()


# ── Template-copy race condition fix (v0.2.2) ─────────────────────────────────

def test_create_module_waits_for_template_copy(tmp_path, monkeypatch, mocker):
    """gh api commits returns 0 on first poll, then 1 — verb waits and succeeds."""
    monkeypatch.chdir(tmp_path)
    mocker.patch("time.sleep")  # don't actually sleep

    # Track how many times we've polled the commits API
    poll_state = {"calls": 0}

    def smart_run(argv, **kw):
        # ── gh repo view → repo does not exist
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            raise CommandError(argv, 1, "", "repository not found")
        # ── gh api repos/.../commits — first call returns 0, second returns 1
        if argv[0] == "gh" and argv[1] == "api" and "commits" in argv[2]:
            poll_state["calls"] += 1
            if poll_state["calls"] == 1:
                return "0"
            return "1"
        if argv[0] == "gh":
            return ""
        # ── git ──────────────────────────────────────────────────────────────
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"
        if argv[1] == "status":
            return "M module.yaml\n"
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    # Should have polled at least twice before content arrived
    assert poll_state["calls"] >= 2, "expected at least two polls of the commits API"


def test_create_module_times_out_when_template_never_copies(tmp_path, monkeypatch, mocker):
    """gh api commits always returns 0 — verb errors with a clear timeout message."""
    monkeypatch.chdir(tmp_path)
    mocker.patch("time.sleep")  # don't actually sleep

    # Make time.time() advance quickly past the 30s deadline after a few ticks
    time_values = iter([0.0, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 31.0, 31.0, 31.0])

    def fake_time():
        try:
            return next(time_values)
        except StopIteration:
            return 31.0

    mocker.patch("woodard_module_helpers.cli.create_module.time.time", side_effect=fake_time)

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            raise CommandError(argv, 1, "", "repository not found")
        if argv[0] == "gh" and argv[1] == "api" and "commits" in argv[2]:
            return "0"  # always empty
        if argv[0] == "gh":
            return ""
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "timed out" in combined.lower() or "timeout" in combined.lower()
    assert "template" in combined.lower()


def test_create_module_resumes_when_local_clone_has_commits(tmp_path, monkeypatch, mocker):
    """Existing local clone already has commits — no wait loop, no error (regression guard)."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")

    wait_loop_entered = {"n": 0}

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"https://github.com/woodard-energy/{slug}.git\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "5\n"  # clone is populated
        if argv[1] == "fetch":
            # If we ever reach fetch, the wait loop was entered unexpectedly
            wait_loop_entered["n"] += 1
            return ""
        if argv[1] == "status":
            return ""
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert wait_loop_entered["n"] == 0, "fetch should not be called when clone has commits"
