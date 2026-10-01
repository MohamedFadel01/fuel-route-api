import pytest

from config.env import env_bool, env_list


class TestEnvBool:
    @pytest.mark.parametrize("raw", ["1", "true", "True", "TRUE", "yes", "on", " true "])
    def test_truthy_values(self, monkeypatch, raw):
        monkeypatch.setenv("FLAG", raw)
        assert env_bool("FLAG") is True

    @pytest.mark.parametrize("raw", ["0", "false", "False", "no", "off", "", "anything-else"])
    def test_falsy_values(self, monkeypatch, raw):
        monkeypatch.setenv("FLAG", raw)
        assert env_bool("FLAG") is False

    def test_missing_variable_uses_default(self, monkeypatch):
        monkeypatch.delenv("FLAG", raising=False)
        assert env_bool("FLAG") is False
        assert env_bool("FLAG", default=True) is True


class TestEnvList:
    def test_splits_on_commas_and_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("HOSTS", "a.com, b.com ,c.com")
        assert env_list("HOSTS") == ["a.com", "b.com", "c.com"]

    def test_ignores_empty_items(self, monkeypatch):
        monkeypatch.setenv("HOSTS", "a.com,, ,b.com,")
        assert env_list("HOSTS") == ["a.com", "b.com"]

    def test_empty_string_gives_empty_list(self, monkeypatch):
        monkeypatch.setenv("HOSTS", "")
        assert env_list("HOSTS") == []

    def test_missing_variable_uses_default(self, monkeypatch):
        monkeypatch.delenv("HOSTS", raising=False)
        assert env_list("HOSTS") == []
        assert env_list("HOSTS", default=["localhost"]) == ["localhost"]

    def test_default_is_not_shared_between_calls(self, monkeypatch):
        monkeypatch.delenv("HOSTS", raising=False)
        env_list("HOSTS").append("mutated")
        assert env_list("HOSTS") == []
