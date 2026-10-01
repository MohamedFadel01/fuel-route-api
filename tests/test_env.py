import pytest

from config.env import env_bool, env_float, env_list, env_str


class TestEnvStr:
    def test_returns_the_stripped_value(self, monkeypatch):
        monkeypatch.setenv("NAME", "  value  ")
        assert env_str("NAME") == "value"

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_values_count_as_unset(self, monkeypatch, raw):
        monkeypatch.setenv("NAME", raw)
        assert env_str("NAME", default="fallback") == "fallback"

    def test_missing_variable_uses_default(self, monkeypatch):
        monkeypatch.delenv("NAME", raising=False)
        assert env_str("NAME") == ""
        assert env_str("NAME", default="fallback") == "fallback"


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


class TestEnvFloat:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("2.5", 2.5), (" 7 ", 7.0), ("0", 0.0), ("-1.5", -1.5), ("1e2", 100.0)],
    )
    def test_reads_a_number(self, monkeypatch, raw, expected):
        monkeypatch.setenv("SECONDS", raw)
        assert env_float("SECONDS", default=10.0) == expected

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_values_count_as_unset(self, monkeypatch, raw):
        monkeypatch.setenv("SECONDS", raw)
        assert env_float("SECONDS", default=10.0) == 10.0

    def test_missing_variable_uses_default(self, monkeypatch):
        monkeypatch.delenv("SECONDS", raising=False)
        assert env_float("SECONDS", default=10.0) == 10.0

    @pytest.mark.parametrize("raw", ["abc", "1,5", "10 seconds", "nan", "inf", "-inf", "NaN"])
    def test_something_that_is_not_a_finite_number_is_an_error_naming_the_variable(
        self, monkeypatch, raw
    ):
        monkeypatch.setenv("SECONDS", raw)
        with pytest.raises(ValueError, match="SECONDS"):
            env_float("SECONDS", default=10.0)
