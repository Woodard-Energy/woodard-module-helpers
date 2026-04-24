import json

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


def test_create_module_json_output(tmp_path, monkeypatch, mocker):
    monkeypatch.chdir(tmp_path)

    from woodard_module_helpers.cli._shell import CommandError

    def smart_run(argv, **kw):
        # gh repo view → repo doesn't exist → create
        if argv[0] == "gh" and argv[1] == "repo" and argv[2] == "view":
            raise CommandError(argv, 1, "", "not found")
        # gh api repos/.../commits — template already populated
        if argv[0] == "gh" and argv[1] == "api" and len(argv) > 2 and "commits" in argv[2]:
            return "1"
        # dev branch doesn't exist
        if argv[0] == "git" and argv[1] == "rev-parse" and "--verify" in argv:
            raise CommandError(argv, 128, "", "")
        # clone has commits — not stuck in race loop
        if argv[0] == "git" and argv[1] == "rev-list" and "--count" in argv and "HEAD" in argv:
            return "3\n"
        # dirty working tree → commit
        if argv[0] == "git" and argv[1] == "status":
            return "M module.yaml\n"
        # no remote dev branch
        if argv[0] == "git" and argv[1] == "ls-remote":
            raise CommandError(argv, 2, "", "")
        return ""

    mocker.patch("woodard_module_helpers.cli.create_module.run", side_effect=smart_run)

    runner = CliRunner()
    r = runner.invoke(app, [
        "create-module", "--domain", "geology", "--name", "well-lookup",
        "--display-name", "Well Lookup", "--json",
    ])
    assert r.exit_code == 0, r.stdout
    payload = json.loads(r.stdout)
    assert payload["status"] == "ok"
    assert payload["verb"] == "create-module"
    assert payload["slug"] == "geology-well-lookup"
    assert payload["repo"] == "woodard-energy/geology-well-lookup"


def test_push_dev_json_output(_module_repo, mocker):
    mocker.patch("woodard_module_helpers.cli.push_dev.run", return_value="")
    mocker.patch(
        "woodard_module_helpers.cli.push_dev._poll_health",
        return_value={"status": "ok", "version": "0.1.1"},
    )

    runner = CliRunner()
    r = runner.invoke(app, ["push-dev", "--message", "wip", "--json"])
    assert r.exit_code == 0, r.stdout
    payload = json.loads(r.stdout)
    assert payload["status"] == "ok"
    assert payload["verb"] == "push-dev"
    assert payload["slug"] == "geology-well-lookup"
    assert payload["version"] == "0.1.1"
    assert payload["dev_url"].startswith("https://wip-dev.woodardenergy.com/")


def test_request_prod_json_output(_module_repo, mocker):
    run_mock = mocker.patch("woodard_module_helpers.cli.request_prod.run")

    def side(argv, **kw):
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return "dev\n"
        if argv == ["git", "fetch", "origin", "dev"]:
            return ""
        if argv == ["git", "status", "--porcelain"]:
            return ""
        if argv[:3] == ["git", "log", "origin/main..dev"]:
            return "abc123 add report route\n"
        if argv[:3] == ["gh", "pr", "create"]:
            return "https://github.com/woodard-energy/geology-well-lookup/pull/1\n"
        return ""

    run_mock.side_effect = side

    runner = CliRunner()
    r = runner.invoke(app, ["request-prod", "--json"])
    assert r.exit_code == 0, r.stdout
    payload = json.loads(r.stdout)
    assert payload["status"] == "ok"
    assert payload["verb"] == "request-prod"
    assert (
        payload["pr_url"]
        == "https://github.com/woodard-energy/geology-well-lookup/pull/1"
    )


def test_error_emits_json_on_failure(_module_repo, mocker):
    from woodard_module_helpers.cli._shell import CommandError

    def side(argv, **kw):
        if argv[:2] == ["uv", "run"] and "pytest" in argv:
            raise CommandError(argv, 1, "", "test failure")
        return ""

    mocker.patch(
        "woodard_module_helpers.cli.push_dev.run", side_effect=side
    )

    runner = CliRunner()
    r = runner.invoke(app, ["push-dev", "--message", "wip", "--json"])
    assert r.exit_code != 0
    payload = json.loads(r.stdout)
    assert payload["status"] == "error"
    assert payload["verb"] == "push-dev"
    assert "test failure" in payload["error"]
