"""A vault's orbit.toml, and orbit's one environment variable."""

from pathlib import Path

import pytest

from orbit import config, settings
from orbit.config import Config, ConfigError

from .conftest import EXAMPLE


def test_the_example_configuration():
    loaded = config.load(EXAMPLE / "99_System" / "orbit.toml")
    assert loaded.me == "per_01M3V0RPR04X2CSM8CEMSVTWVA"
    assert (loaded.host, loaded.port) == ("127.0.0.1", 8775)
    assert loaded.free_mail_domains == frozenset(config.FREE_MAIL_DOMAINS)
    assert loaded.role_addresses == frozenset(config.ROLE_ADDRESSES)


def test_the_template_is_the_examples():
    text = (EXAMPLE / "99_System" / "orbit.toml").read_text(encoding="utf-8")
    assert config.template("per_01M3V0RPR04X2CSM8CEMSVTWVA") == text


def test_defaults_without_a_file(tmp_path):
    assert config.load(tmp_path / "orbit.toml") == Config()


def test_defaults_for_what_a_file_leaves_out(tmp_path):
    path = tmp_path / "orbit.toml"
    path.write_text('[identity]\nrole_addresses = ["Info", " "]\n', encoding="utf-8")
    assert config.load(path) == Config(role_addresses=frozenset({"info"}))


@pytest.mark.parametrize(
    "text, message",
    [
        ("me = [", "orbit.toml: "),
        ('me = "Max"', "me must be the id of Me.md"),
        ('server = "x"', r"server must be a table, \[server\]"),
        ("[server]\nport = 0", "server.port must be a port number"),
        ("[server]\nport = true", "server.port must be a port number"),
        ("[server]\nport = '8775'", "server.port must be a port number"),
        ("[server]\nhost = 1", "server.host must be text"),
        ("[identity]\nrole_addresses = 'info'", "identity.role_addresses must be a list of text"),
        ("colour = 1", "unknown setting colour"),
        ("[server]\nhots = 'x'", "unknown setting server.hots"),
    ],
)
def test_refuses_what_it_cannot_use(tmp_path, text, message):
    path = tmp_path / "orbit.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        config.load(path)


def test_the_tools_to_serve(tmp_path):
    path = tmp_path / "orbit.toml"
    assert config.load(path).tools is None  # all of them
    path.write_text('[server]\ntools = ["read", " write "]\n', encoding="utf-8")
    assert config.load(path).tools == ("read", "write")
    path.write_text('[server]\ntools = "read"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"server\.tools must be a list of text"):
        config.load(path)


def test_reads_a_file_saved_with_a_byte_order_mark(tmp_path):
    path = tmp_path / "orbit.toml"
    path.write_text("[server]\nport = 9000\n", encoding="utf-8-sig")  # as PowerShell and some editors save UTF-8
    assert config.load(path).port == 9000


def test_refuses_a_file_that_is_not_utf8(tmp_path):
    path = tmp_path / "orbit.toml"
    path.write_text('[identity]\nrole_addresses = ["bür"]\n', encoding="cp1252")
    with pytest.raises(ConfigError, match=r"orbit\.toml isn't UTF-8 text; save it as UTF-8"):
        config.load(path)


def test_orbit_home_may_start_with_a_tilde():
    # An MCP client's env block, and PowerShell, pass "~" on as it is; it means the home folder there too.
    assert settings.Settings.from_env({"ORBIT_HOME": "~/orbit-indexes"}).home == Path.home() / "orbit-indexes"


def test_orbit_home(tmp_path):
    assert settings.Settings.from_env({"ORBIT_HOME": str(tmp_path)}).home == tmp_path
    assert settings.Settings.from_env({"ORBIT_HOME": ""}).home == Path.home() / ".orbit"
    assert settings.Settings.from_env({}).home == Path.home() / ".orbit"


def test_current_settings_are_read_once(monkeypatch, tmp_path):
    settings.current.cache_clear()
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path))
    assert settings.current().home == tmp_path
    monkeypatch.setenv("ORBIT_HOME", str(tmp_path / "other"))
    assert settings.current().home == tmp_path
    settings.current.cache_clear()
