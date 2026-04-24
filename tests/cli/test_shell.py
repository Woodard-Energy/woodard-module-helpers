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


def test_command_error_falls_back_to_stdout_when_stderr_empty(mocker):
    """When stderr is empty (e.g. git fatal: goes to stdout), stdout is used."""
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["git", "push", "origin", "dev"],
            returncode=128,
            stdout="fatal: repository not found\n",
            stderr="",
        ),
    )
    with pytest.raises(CommandError) as exc:
        run(["git", "push", "origin", "dev"])
    err = str(exc.value)
    assert "fatal: repository not found" in err
    assert "128" in err
    assert exc.value.returncode == 128
    assert exc.value.stdout == "fatal: repository not found\n"
    assert exc.value.stderr == ""


def test_command_error_shows_no_output_when_both_empty(mocker):
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["git", "commit"], returncode=1, stdout="", stderr=""
        ),
    )
    with pytest.raises(CommandError) as exc:
        run(["git", "commit"])
    assert "(no output)" in str(exc.value)


def test_command_error_includes_command_prefix():
    """CommandError message starts with up to 4 argv tokens."""
    err = CommandError(["gh", "repo", "clone", "woodard-energy/foo"], 1, "", "clone failed")
    assert str(err).startswith("gh repo clone woodard-energy/foo")


def test_command_error_truncates_long_output():
    long_output = "x" * 1000
    err = CommandError(["git", "push"], 1, long_output, "")
    assert len(str(err)) < 700  # 500-char cap + prefix overhead
