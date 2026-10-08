"""Role-named REVERIE_* settings and their old LAYA_AGENT_* aliases. Offline."""

import pytest
from test_control import session

from reverie import settings
from reverie.control.session import Session, escalation_disabled


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for new, old in settings.RENAMED.items():
        monkeypatch.delenv(new, raising=False)
        monkeypatch.delenv(old, raising=False)


def test_every_old_name_still_works_as_an_alias(monkeypatch):
    for new, old in settings.RENAMED.items():
        monkeypatch.setenv(old, "from-old")
        assert settings.setting(new, "default") == "from-old", old


def test_the_new_name_wins_over_the_old_one(monkeypatch):
    monkeypatch.setenv("LAYA_AGENT_ENGINE", "laya")
    monkeypatch.setenv("REVERIE_DECISION_ENGINE", "jev")
    assert settings.setting("REVERIE_DECISION_ENGINE") == "jev"


def test_empty_counts_as_unset(monkeypatch):
    monkeypatch.setenv("REVERIE_SESSION", "")
    monkeypatch.setenv("LAYA_AGENT_SESSION", "old")
    assert settings.setting("REVERIE_SESSION", "default") == "old"
    monkeypatch.delenv("LAYA_AGENT_SESSION")
    assert settings.setting("REVERIE_SESSION", "default") == "default"


def test_escalation_switch_reads_both_names(monkeypatch):
    assert not escalation_disabled()
    monkeypatch.setenv("LAYA_AGENT_MERCURY", "off")
    assert escalation_disabled()
    monkeypatch.setenv("REVERIE_ESCALATION", "on")
    assert not escalation_disabled()


def test_the_pilot_endpoint_reads_new_then_old_names(monkeypatch):
    from reverie import model

    for name in ("TEXT_MODEL_PROVIDER", "TEXT_MODEL_BASE_URL", "TEXT_MODEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LAYA_AGENT_PILOT_BASE_URL", "https://old.example.com/v1")
    monkeypatch.setenv("LAYA_AGENT_PILOT_API_KEY", "old-key")
    assert model.endpoint("pilot")[:2] == ("https://old.example.com/v1", "old-key")
    monkeypatch.setenv("REVERIE_PILOT_BASE_URL", "https://new.example.com/v1")
    assert model.endpoint("pilot")[:2] == ("https://new.example.com/v1", "old-key")


def test_config_accepts_old_names_and_sets_the_new_one(tmp_path, monkeypatch):
    s = session(tmp_path)
    s.log = lambda *a, **kw: None
    s.summary = lambda: {}
    assert s.cmd_config("LAYA_AGENT_STALL_SECONDS", "120")["config"] == {"REVERIE_STALL_SECONDS": "120"}
    assert settings.setting("REVERIE_STALL_SECONDS") == "120"
    monkeypatch.delenv("REVERIE_STALL_SECONDS")


def test_the_old_engine_name_mercury_still_selects_the_escalation_model():
    assert Session.ENGINE_ALIASES["mercury"] == "escalation" and "escalation" in Session.ENGINES
