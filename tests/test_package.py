"""The installed package: its version, and the `orbit` command."""

import runpy
import sys
from importlib.metadata import version

import pytest

import orbit
from orbit import cli


def test_version_is_the_distributions():
    assert orbit.__version__ == version("orbit-crm")


def test_version_option(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out == f"orbit {orbit.__version__}\n"


def test_without_a_command_it_shows_help(capsys):
    assert cli.main([]) == 0
    assert "usage: orbit" in capsys.readouterr().out


def test_runs_as_a_module(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["orbit", "--version"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("orbit", run_name="__main__")
    assert stop.value.code == 0
    assert capsys.readouterr().out.startswith("orbit ")
