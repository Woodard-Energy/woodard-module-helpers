import json

import pytest
from typer.testing import CliRunner

from woodard_module_helpers.cli import app

REPO_LIST_JSON = json.dumps([
    {"name": "intelligence-platform", "description": "shell", "visibility": "private"},
    {"name": "module-helpers", "description": "helpers", "visibility": "private"},
    {"name": "module-template", "description": "template", "visibility": "private"},
    {"name": "claude-platform-skills", "description": "skills plugin", "visibility": "private"},
    {"name": "reservoir-model-optimizer", "description": "Acq cashflow", "visibility": "private"},
    {"name": "geology-well-lookup", "description": "Well API lookup", "visibility": "private"},
])


@pytest.fixture
def _fake_shell(mocker):
    """Default: gh repo list returns full list; all other calls succeed empty."""
    def side(argv, **kw):
        if argv[:3] == ["gh", "repo", "list"]:
            return REPO_LIST_JSON
        if argv[:2] == ["git", "branch"]:
            return "  origin/main\n* origin/dev\n"
        return ""
    return mocker.patch("woodard_module_helpers.cli.clone_module.run", side_effect=side)


def test_direct_mode_with_valid_slug(_fake_shell, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        app, ["clone-module", "--slug", "reservoir-model-optimizer", "--dest", str(tmp_path)]
    )
    assert r.exit_code == 0, r.stdout

    argvs = [c.args[0] for c in _fake_shell.call_args_list]
    # gh repo list was called (to validate slug)
    assert any(a[:3] == ["gh", "repo", "list"] for a in argvs)
    # gh repo clone was called with full slug
    assert any(
        a[:3] == ["gh", "repo", "clone"]
        and "woodard-energy/reservoir-model-optimizer" in a
        for a in argvs
    )


def test_direct_mode_rejects_invalid_slug(_fake_shell, tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["clone-module", "--slug", "not-a-real-module", "--dest", str(tmp_path)])
    assert r.exit_code != 0


def test_direct_mode_rejects_infra_slug(_fake_shell, tmp_path):
    """Users shouldn't clone shell/helpers/template/skills via this verb."""
    runner = CliRunner()
    r = runner.invoke(
        app, ["clone-module", "--slug", "intelligence-platform", "--dest", str(tmp_path)]
    )
    assert r.exit_code != 0


def test_json_output_on_success(_fake_shell, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, [
        "clone-module",
        "--slug", "reservoir-model-optimizer",
        "--dest", str(tmp_path),
        "--json",
    ])
    assert r.exit_code == 0, r.stdout
    payload = json.loads(r.stdout)
    assert payload["status"] == "ok"
    assert payload["verb"] == "clone-module"
    assert payload["slug"] == "reservoir-model-optimizer"
    assert payload["repo"] == "woodard-energy/reservoir-model-optimizer"


def test_target_already_exists_fails(_fake_shell, tmp_path):
    existing = tmp_path / "reservoir-model-optimizer"
    existing.mkdir()
    runner = CliRunner()
    r = runner.invoke(
        app, ["clone-module", "--slug", "reservoir-model-optimizer", "--dest", str(tmp_path)]
    )
    assert r.exit_code != 0
    # Should not attempt clone if target exists
    argvs = [c.args[0] for c in _fake_shell.call_args_list]
    assert not any(a[:3] == ["gh", "repo", "clone"] for a in argvs)


def test_interactive_mode_prompts_for_selection(tmp_path, monkeypatch, mocker):
    """When no --slug is given, list modules and prompt user."""
    monkeypatch.chdir(tmp_path)
    run_mock = mocker.patch(
        "woodard_module_helpers.cli.clone_module.run"
    )

    def side(argv, **kw):
        if argv[:3] == ["gh", "repo", "list"]:
            return REPO_LIST_JSON
        if argv[:2] == ["git", "branch"]:
            return "  origin/main\n"
        return ""
    run_mock.side_effect = side

    runner = CliRunner()
    # typer.testing passes input= to typer.prompt
    r = runner.invoke(
        app,
        ["clone-module", "--dest", str(tmp_path)],
        input="reservoir-model-optimizer\n",
    )
    assert r.exit_code == 0, r.stdout
    # Output listed the module options
    assert "reservoir-model-optimizer" in r.stdout
    assert "geology-well-lookup" in r.stdout
    # Clone fired for the chosen one
    argvs = [c.args[0] for c in run_mock.call_args_list]
    assert any(
        a[:3] == ["gh", "repo", "clone"]
        and "woodard-energy/reservoir-model-optimizer" in a
        for a in argvs
    )
