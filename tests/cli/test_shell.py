import subprocess

import pytest

from woodard_module_helpers.cli._shell import CommandError, run


def test_run_returns_stdout_on_success(mocker):
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["echo", "hi"], returncode=0, stdout="hi\n", stderr=""
        ),
    )
    result = run(["echo", "hi"])
    assert result == "hi\n"


def test_run_raises_on_nonzero_exit(mocker):
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["false"], returncode=1, stdout="", stderr="boom"
        ),
    )
    with pytest.raises(CommandError) as exc:
        run(["false"])
    assert "boom" in str(exc.value)


def test_run_captures_stderr_into_error(mocker):
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["gh", "repo", "create"], returncode=1, stdout="", stderr="name exists"
        ),
    )
    with pytest.raises(CommandError) as exc:
        run(["gh", "repo", "create"])
    assert "name exists" in str(exc.value)
    assert exc.value.returncode == 1
