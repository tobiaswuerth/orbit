"""orbit's one environment variable, ORBIT_HOME, read once per process. Every module asks `current()` instead of
reading the environment itself."""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    home: Path  # ORBIT_HOME: where the indexes and locks live, outside every vault

    @classmethod
    def from_env(cls, environ=os.environ):
        """The settings an environment gives. An empty variable counts as unset; a leading ~ is the home folder."""
        return cls(home=Path(environ.get("ORBIT_HOME") or Path.home() / ".orbit").expanduser())


@cache
def current():
    """This process's settings, from its environment, read on first use."""
    return Settings.from_env()
