import datetime
import shutil
from pathlib import Path

import pytest

from orbit import settings
from orbit.crm import Crm

VAULTS = Path(__file__).parent / "vaults"
EXAMPLE = VAULTS / "example"  # the format reference: every note type as orbit writes it
NOW = datetime.datetime(2026, 10, 22, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A temporary ORBIT_HOME for every test, so no test touches a real index."""
    path = tmp_path / "home"
    monkeypatch.setenv("ORBIT_HOME", str(path))
    settings.current.cache_clear()
    yield path
    settings.current.cache_clear()


@pytest.fixture
def example(tmp_path):
    """A copy of the example vault."""
    return Path(shutil.copytree(EXAMPLE, tmp_path / "vault"))


@pytest.fixture
def crm(example, home):
    """The example vault, opened and indexed, at a fixed time."""
    with Crm(example, home, now=lambda: NOW) as opened:
        opened.refresh()
        yield opened
