from zengrowth.config import Settings


def test_settings_accept_csv_list_env_values(monkeypatch):
    monkeypatch.setenv("USER_TARGET_ROLES", "Head of AI, Director of AI")
    monkeypatch.setenv("USER_TARGET_SECTORS", "AI, FinTech")
    monkeypatch.setenv("ATS_BOARDS", "greenhouse:anthropic, lever:netflix")

    settings = Settings(_env_file=None)

    assert settings.user_target_roles == ["Head of AI", "Director of AI"]
    assert settings.user_target_sectors == ["AI", "FinTech"]
    assert settings.ats_boards == ["greenhouse:anthropic", "lever:netflix"]


def test_settings_accept_json_list_env_values(monkeypatch):
    monkeypatch.setenv("ATS_BOARDS", '["greenhouse:anthropic", "lever:netflix"]')

    settings = Settings(_env_file=None)

    assert settings.ats_boards == ["greenhouse:anthropic", "lever:netflix"]


def test_auth_and_feature_defaults_are_dev_safe():
    settings = Settings(_env_file=None)

    assert settings.zengrowth_operator_password_hash is None
    assert settings.zengrowth_session_secret is None
    assert settings.zengrowth_require_https is False
    assert settings.feature_public_observability is True
    assert settings.feature_sse is True


def test_require_operator_auth_raises_when_unset():
    import pytest

    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError) as exc:
        settings.require_operator_auth()
    assert "ZENGROWTH_OPERATOR_PASSWORD_HASH" in str(exc.value)
    assert "ZENGROWTH_SESSION_SECRET" in str(exc.value)


def test_require_operator_auth_returns_pair_when_set(monkeypatch):
    monkeypatch.setenv("ZENGROWTH_OPERATOR_PASSWORD_HASH", "pbkdf2_sha256$1$salt$hash")
    monkeypatch.setenv("ZENGROWTH_SESSION_SECRET", "topsecret")

    settings = Settings(_env_file=None)

    assert settings.require_operator_auth() == ("pbkdf2_sha256$1$salt$hash", "topsecret")
