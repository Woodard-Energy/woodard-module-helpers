"""Tests for the convert-to-platform verb.

Covers both original behaviour and the idempotency/safe-resume logic
added in v0.2.1.

NOTE: convert_to_platform delegates all subprocess calls to helper
functions imported from create_module, so the correct mock target is
`woodard_module_helpers.cli.create_module.run` — not convert_to_platform.run.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._shell import CommandError

# Canonical mock target — all subprocess calls flow through create_module.run.
_RUN = "woodard_module_helpers.cli.create_module.run"


@pytest.fixture(autouse=True)
def _mock_domains(mocker):
    mocker.patch(
        "woodard_module_helpers.cli.convert_to_platform.fetch_valid_domains",
        return_value=("drilling", "geology", "land", "midstream", "reservoir"),
    )


@pytest.fixture
def _source_project(tmp_path):
    src = tmp_path / "my-experiment"
    (src / "app").mkdir(parents=True)
    (src / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (src / "pyproject.toml").write_text(
        '[project]\nname = "my-experiment"\nversion = "0.3.0"\n',
        encoding="utf-8",
    )
    (src / "README.md").write_text("# My Experiment\n", encoding="utf-8")
    return src


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


def _make_smart_run(*, repo_view_raises=True, remote_url=None, dev_exists=False,
                    status_output="M module.yaml\n", clone_side_effect=None):
    """Return a smart_run callable for convert-to-platform tests."""
    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            if repo_view_raises:
                raise CommandError(argv, 1, "", "not found")
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "clone":
            if clone_side_effect:
                clone_side_effect()
            return ""
        if argv[0] == "gh":
            return ""
        if argv[1] == "remote" and argv[2] == "get-url":
            return f"{remote_url or ''}\n"
        if argv[1] == "rev-parse" and "--verify" in argv:
            if dev_exists:
                return "abc1234\n"
            raise CommandError(argv, 128, "", "")
        if argv[1] == "status":
            return status_output
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""
    return smart_run


# ── Original validation tests ─────────────────────────────────────────────────

def test_refuses_source_without_app_dir(tmp_path):
    """Validation happens before any subprocess call."""
    src = tmp_path / "bad"
    src.mkdir()
    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(src),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    assert "app/" in r.stdout or "app/" in r.stderr


def test_rejects_invalid_domain(_source_project):
    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "bogus",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0


def test_happy_path_creates_repo_and_copies_files(
    _source_project, tmp_path, monkeypatch, mocker
):
    monkeypatch.chdir(tmp_path)

    def clone_creates_dest():
        dest = Path("geology-well-lookup")
        dest.mkdir(exist_ok=True)
        (dest / "module.yaml").write_text(
            "display_name: REPLACE_ME\nname: REPLACE_ME\ndomain: REPLACE_ME\n",
            encoding="utf-8",
        )
        (dest / "pyproject.toml").write_text(
            '[project]\nname = "REPLACE_ME"\n', encoding="utf-8",
        )
        (dest / ".claude").mkdir()
        (dest / ".claude" / "CLAUDE.md").write_text(
            "# Module: REPLACE_ME\n", encoding="utf-8",
        )

    mocker.patch(
        _RUN,
        side_effect=_make_smart_run(
            repo_view_raises=True,
            clone_side_effect=clone_creates_dest,
        ),
    )

    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout

    dest = tmp_path / "geology-well-lookup"
    assert (dest / "app" / "main.py").exists()
    assert "FastAPI" in (dest / "app" / "main.py").read_text(encoding="utf-8")
    # Placeholders patched.
    assert "name: well-lookup" in (dest / "module.yaml").read_text(encoding="utf-8")
    assert 'name = "geology-well-lookup"' in (dest / "pyproject.toml").read_text(encoding="utf-8")


# ── Idempotency: source dir guard ─────────────────────────────────────────────

def test_convert_stops_when_source_dir_missing(tmp_path, monkeypatch):
    """If source dir doesn't exist (e.g. moved after partial run) → clear error."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(tmp_path / "nonexistent"),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "does not exist" in combined.lower()


# ── Idempotency: Step A (GitHub repo) ────────────────────────────────────────

def test_convert_resumes_when_repo_exists_from_template(
    _source_project, tmp_path, monkeypatch, mocker
):
    """GitHub repo already exists from module-template → skip create, resume clone."""
    monkeypatch.chdir(tmp_path)
    created = {"n": 0}

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "create":
            created["n"] += 1
            return ""
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "clone":
            dest = tmp_path / "geology-well-lookup"
            dest.mkdir(exist_ok=True)
            (dest / "module.yaml").write_text(
                "display_name: REPLACE_ME\nname: REPLACE_ME\ndomain: REPLACE_ME\n"
            )
            (dest / "pyproject.toml").write_text('[project]\nname = "REPLACE_ME"\n')
            (dest / ".claude").mkdir(exist_ok=True)
            (dest / ".claude" / "CLAUDE.md").write_text("# Module: REPLACE_ME\n")
            return ""
        if argv[0] == "gh":
            return ""
        if argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        if argv[1] == "status":
            return "M module.yaml\n"
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch(_RUN, side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert created["n"] == 0, "gh repo create should have been skipped"
    assert "resuming" in r.stdout.lower() or "already exists" in r.stdout.lower()


def test_convert_refuses_non_template_repo(
    _source_project, tmp_path, monkeypatch, mocker
):
    """Existing repo not from our template → exit 2."""
    monkeypatch.chdir(tmp_path)

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({"templateRepository": None})
        return ""

    mocker.patch(_RUN, side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 2
    combined = r.stdout + (r.stderr or "")
    assert "refusing" in combined.lower()


# ── Idempotency: Step B (local clone) ────────────────────────────────────────

def test_convert_resumes_when_local_clone_exists_with_correct_remote(
    _source_project, tmp_path, monkeypatch, mocker
):
    """Local .git/ exists with matching remote → clone step skipped."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")
    # Template files already present (partially-applied state)
    (repo_dir / "module.yaml").write_text(
        "display_name: REPLACE_ME\nname: REPLACE_ME\ndomain: REPLACE_ME\n"
    )
    (repo_dir / "pyproject.toml").write_text('[project]\nname = "REPLACE_ME"\n')
    (repo_dir / ".claude").mkdir()
    (repo_dir / ".claude" / "CLAUDE.md").write_text("# Module: REPLACE_ME\n")

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
        if argv[1] == "status":
            return "M module.yaml\n"
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch(_RUN, side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert cloned["n"] == 0, "gh repo clone should have been skipped"
    assert "resuming" in r.stdout.lower()


def test_convert_refuses_local_dir_with_different_remote(
    _source_project, tmp_path, monkeypatch, mocker
):
    """Local .git/ points at a different remote → stop."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, "https://github.com/someone-else/other.git")

    def smart_run(argv, **kw):
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            return json.dumps({
                "templateRepository": {"full_name": "Woodard-Energy/module-template"}
            })
        if argv[1] == "remote" and argv[2] == "get-url":
            return "https://github.com/someone-else/other.git\n"
        return ""

    mocker.patch(_RUN, side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code != 0
    combined = r.stdout + (r.stderr or "")
    assert "refusing" in combined.lower()


# ── Idempotency: Step E (commit) ─────────────────────────────────────────────

def test_convert_skips_commit_when_nothing_to_commit(
    _source_project, tmp_path, monkeypatch, mocker
):
    """Working tree clean after patching → skip commit, no error."""
    monkeypatch.chdir(tmp_path)
    slug = "geology-well-lookup"
    repo_dir = tmp_path / slug
    repo_dir.mkdir()
    _make_git_dir(repo_dir, f"https://github.com/woodard-energy/{slug}.git")
    (repo_dir / "module.yaml").write_text(
        "display_name: Well Lookup\nname: well-lookup\ndomain: geology\n"
    )
    (repo_dir / "pyproject.toml").write_text('[project]\nname = "geology-well-lookup"\n')
    (repo_dir / ".claude").mkdir()
    (repo_dir / ".claude" / "CLAUDE.md").write_text("# Module: Well Lookup\n")

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
            raise CommandError(argv, 128, "", "")
        if argv[1] == "status":
            return ""  # clean
        if argv[1] == "commit":
            committed["n"] += 1
            return ""
        if argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch(_RUN, side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "convert-to-platform",
        "--source", str(_source_project),
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout
    assert committed["n"] == 0, "git commit should have been skipped"
    combined = r.stdout + (r.stderr or "")
    assert "clean" in combined.lower() or "skipping commit" in combined.lower()
