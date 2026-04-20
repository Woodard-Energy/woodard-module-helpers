import pytest
from typer.testing import CliRunner

from woodard_module_helpers.cli import app


@pytest.fixture
def _module_repo(tmp_path, monkeypatch):
    repo = tmp_path / "geology-well-lookup"
    repo.mkdir()
    (repo / "module.yaml").write_text(
        "name: well-lookup\ndomain: geology\nversion: 0.1.1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    return repo


def test_refuses_when_not_on_dev(_module_repo, mocker):
    run_mock = mocker.patch("woodard_module_helpers.cli.request_prod.run")

    def side(argv, **kw):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return "feature-branch\n"
        return ""

    run_mock.side_effect = side

    runner = CliRunner()
    r = runner.invoke(app, ["request-prod"])
    assert r.exit_code != 0
    assert "dev" in r.stdout.lower() or "dev" in r.stderr.lower()


def test_refuses_when_dev_not_up_to_date(_module_repo, mocker):
    run_mock = mocker.patch("woodard_module_helpers.cli.request_prod.run")

    def side(argv, **kw):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return "dev\n"
        if argv == ["git", "fetch", "origin", "dev"]:
            return ""
        if argv == ["git", "status", "--porcelain"]:
            return " M app/main.py\n"  # dirty
        return ""

    run_mock.side_effect = side

    runner = CliRunner()
    r = runner.invoke(app, ["request-prod"])
    assert r.exit_code != 0


def test_happy_path_opens_pr(_module_repo, mocker):
    run_mock = mocker.patch("woodard_module_helpers.cli.request_prod.run")

    def side(argv, **kw):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return "dev\n"
        if argv == ["git", "fetch", "origin", "dev"]:
            return ""
        if argv == ["git", "status", "--porcelain"]:
            return ""
        if argv[:3] == ["git", "log", "origin/main..dev"]:
            return "abc123 add report route\ndef456 fix prefix\n"
        if argv[:3] == ["gh", "pr", "create"]:
            return "https://github.com/woodard-energy/geology-well-lookup/pull/1\n"
        return ""

    run_mock.side_effect = side

    runner = CliRunner()
    r = runner.invoke(app, ["request-prod"])
    assert r.exit_code == 0, r.stdout
    assert "pull/1" in r.stdout

    # PR was created with --base main --head dev and a body.
    pr_calls = [
        c for c in run_mock.call_args_list
        if c.args[0][:3] == ["gh", "pr", "create"]
    ]
    assert len(pr_calls) == 1
    argv = pr_calls[0].args[0]
    assert "--base" in argv and "main" in argv
    assert "--head" in argv and "dev" in argv
    assert "--title" in argv
    assert "--body" in argv
