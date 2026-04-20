import pytest
from typer.testing import CliRunner

from woodard_module_helpers.cli import app


@pytest.fixture
def _fake_shell(mocker):
    """Mock _shell.run so no real subprocess calls happen."""
    return mocker.patch("woodard_module_helpers.cli.create_module.run", return_value="")


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


def test_happy_path_runs_expected_commands(_fake_shell, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module",
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout

    argvs = [c.args[0] for c in _fake_shell.call_args_list]
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


def test_patches_module_yaml_with_inputs(tmp_path, monkeypatch, mocker):
    """Simulate a cloned repo with template placeholders; verify patching."""
    monkeypatch.chdir(tmp_path)
    repo_dir = tmp_path / "geology-well-lookup"
    repo_dir.mkdir()
    (repo_dir / "module.yaml").write_text(
        "name: REPLACE_ME\ndomain: REPLACE_ME\ndisplay_name: REPLACE_ME\n"
    )
    (repo_dir / "pyproject.toml").write_text(
        '[project]\nname = "REPLACE_ME"\n'
    )
    (repo_dir / ".claude").mkdir()
    (repo_dir / ".claude" / "CLAUDE.md").write_text(
        "# Module: REPLACE_ME\n"
    )
    mocker.patch("woodard_module_helpers.cli.create_module.run", return_value="")

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module",
        "--domain", "geology",
        "--name", "well-lookup",
        "--display-name", "Well Lookup",
    ])
    assert r.exit_code == 0, r.stdout

    mod_yaml = (repo_dir / "module.yaml").read_text()
    assert "name: well-lookup" in mod_yaml
    assert "domain: geology" in mod_yaml
    assert "display_name: Well Lookup" in mod_yaml
    pyproj = (repo_dir / "pyproject.toml").read_text()
    assert 'name = "geology-well-lookup"' in pyproj
    claude = (repo_dir / ".claude" / "CLAUDE.md").read_text()
    assert "# Module: Well Lookup" in claude
