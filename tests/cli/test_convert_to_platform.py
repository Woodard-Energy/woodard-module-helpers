from pathlib import Path

import pytest
from typer.testing import CliRunner

from woodard_module_helpers.cli import app


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


def test_refuses_source_without_app_dir(tmp_path, mocker):
    src = tmp_path / "bad"
    src.mkdir()
    mocker.patch(
        "woodard_module_helpers.cli.convert_to_platform.run", return_value=""
    )

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


def test_rejects_invalid_domain(_source_project, mocker):
    mocker.patch(
        "woodard_module_helpers.cli.convert_to_platform.run", return_value=""
    )
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
    run_mock = mocker.patch(
        "woodard_module_helpers.cli.convert_to_platform.run", return_value=""
    )

    # Simulate that after `gh repo create` + clone, we end up with a dest dir.
    def side(argv, **kw):
        if argv[:3] == ["gh", "repo", "clone"]:
            # Create the clone target directory with template-shaped files.
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
        return ""

    run_mock.side_effect = side

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

    # gh repo create used template.
    argvs = [c.args[0] for c in run_mock.call_args_list]
    assert any(
        a[:3] == ["gh", "repo", "create"]
        and "--template" in a
        and "woodard-energy/geology-well-lookup" in a
        for a in argvs
    ), argvs
