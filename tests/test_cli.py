"""The command line entry point.

`python -m app.cli build` is the first command anyone runs, usually with
whichever `python` is on PATH. When that is not the project virtualenv the
failure is a bare ModuleNotFoundError from deep inside the loader, which reads
as a bug in the code rather than as a missing environment.
"""
from __future__ import annotations

import sys

import pytest

from app import cli


def test_a_missing_dependency_names_the_interpreter_and_the_fix() -> None:
    hint = cli._venv_hint(ModuleNotFoundError("No module named 'duckdb'", name="duckdb"))

    assert "'duckdb' is not installed" in hint
    # The interpreter actually running, so the reader can see it is the wrong one.
    assert sys.executable in hint
    assert "not the" in hint and "project virtualenv" in hint
    # And the exact command that works.
    assert "-m app.cli build" in hint
    assert ".venv" in hint


def test_it_offers_to_create_the_virtualenv_only_when_there_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    missing = ModuleNotFoundError("No module named 'duckdb'", name="duckdb")

    # This project has a .venv, so the message points at it and stops there.
    assert "python -m venv .venv" not in cli._venv_hint(missing)

    # A checkout without one needs the install step spelled out as well.
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    fresh = cli._venv_hint(missing)
    assert "python -m venv .venv" in fresh
    assert "pip install -r requirements.txt" in fresh


def test_build_exits_two_when_the_dependencies_are_absent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 is "you invoked it wrong", not 1, which means the build failed."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "app.ingest.loaders":
            raise ModuleNotFoundError("No module named 'duckdb'", name="duckdb")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    code = cli.main(["build"])

    assert code == 2
    assert "'duckdb' is not installed" in capsys.readouterr().err
