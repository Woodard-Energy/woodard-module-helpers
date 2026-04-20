import httpx
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


def test_blocks_push_when_tests_fail(_module_repo, mocker):
    from woodard_module_helpers.cli._shell import CommandError
    run_mock = mocker.patch("woodard_module_helpers.cli.push_dev.run")

    def side(argv, **kw):
        if argv[:2] == ["uv", "run"] and "pytest" in argv:
            raise CommandError(argv, 1, "1 test failed")
        return ""

    run_mock.side_effect = side

    runner = CliRunner()
    r = runner.invoke(app, ["push-dev", "--message", "wip"])
    assert r.exit_code != 0
    # No git push happened.
    assert not any(
        c.args[0][:2] == ["git", "push"] for c in run_mock.call_args_list
    )


def test_happy_path_runs_tests_commits_pushes_polls(_module_repo, mocker):
    mocker.patch("woodard_module_helpers.cli.push_dev.run", return_value="")
    poll = mocker.patch(
        "woodard_module_helpers.cli.push_dev._poll_health",
        return_value={"status": "ok", "version": "0.1.1"},
    )

    runner = CliRunner()
    r = runner.invoke(app, ["push-dev", "--message", "add report route"])
    assert r.exit_code == 0, r.stdout
    poll.assert_called_once()
    assert "0.1.1" in r.stdout
    assert "wip-dev.woodardenergy.com/geology/well-lookup" in r.stdout


def test_poll_health_reports_success(_module_repo, mocker):
    from woodard_module_helpers.cli.push_dev import _poll_health

    def fake_get(url, **kw):
        return httpx.Response(200, json={"status": "ok", "version": "0.1.1"})

    mocker.patch("httpx.get", side_effect=fake_get)
    result = _poll_health(
        "https://wip-dev.woodardenergy.com/geology/well-lookup/_health",
        expected_version="0.1.1",
        timeout_s=5,
    )
    assert result == {"status": "ok", "version": "0.1.1"}


def test_poll_health_times_out_on_stale_version(_module_repo, mocker):
    from woodard_module_helpers.cli.push_dev import HealthPollTimeout, _poll_health

    mocker.patch(
        "httpx.get",
        side_effect=lambda url, **kw: httpx.Response(
            200, json={"status": "ok", "version": "0.1.0"}
        ),
    )
    mocker.patch("time.sleep", return_value=None)

    with pytest.raises(HealthPollTimeout):
        _poll_health(
            "https://wip-dev.woodardenergy.com/geology/well-lookup/_health",
            expected_version="0.1.1",
            timeout_s=1,
        )
