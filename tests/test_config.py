"""Tests for the config env-var helpers."""

from __future__ import annotations

from wealth_agent import config


def test_env_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("WEALTH_TEST_VALUE", raising=False)
    assert config.env("WEALTH_TEST_VALUE", "fallback") == "fallback"


def test_env_reads_value(monkeypatch):
    monkeypatch.setenv("WEALTH_TEST_VALUE", "actual")
    assert config.env("WEALTH_TEST_VALUE", "fallback") == "actual"


def test_env_int_parses_and_falls_back(monkeypatch):
    monkeypatch.setenv("WEALTH_TEST_INT", "42")
    assert config.env_int("WEALTH_TEST_INT", 7) == 42
    monkeypatch.setenv("WEALTH_TEST_INT", "not-a-number")
    assert config.env_int("WEALTH_TEST_INT", 7) == 7


def test_env_bool_accepts_truthy_strings(monkeypatch):
    for truthy in ("true", "1", "YES", "On"):
        monkeypatch.setenv("WEALTH_TEST_BOOL", truthy)
        assert config.env_bool("WEALTH_TEST_BOOL", False) is True
    for falsy in ("false", "0", "no", ""):
        monkeypatch.setenv("WEALTH_TEST_BOOL", falsy)
        assert config.env_bool("WEALTH_TEST_BOOL", True) is (falsy == "")
