import pytest

from app.core.config import ConfigError, load_settings

SECRET = "Sup3r-Secret-Pa55"

VALID = {
    "mongodb_uri": "mongodb+srv://cluster0.example.mongodb.net/?retryWrites=true&w=majority",
    "game_data_db_user": "game_user",
    "game_data_db_password": SECRET,
    "mongodb_db_name_prod": "operation_zero",
    "mongodb_db_name_dev": "operation_zero_dev",
    "mongodb_db_name_test": "operation_zero_test",
    "jwt_secret": "x" * 32,
}

DB_ENV_VARS = (
    "JWT_SECRET",
    "APP_ENV",
    "MONGODB_URI",
    "GAME_DATA_DB_USER",
    "GAME_DATA_DB_PASSWORD",
    "MONGODB_DB_NAME_PROD",
    "MONGODB_DB_NAME_DEV",
    "MONGODB_DB_NAME_TEST",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """These tests must not see real environment variables."""
    for name in DB_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**overrides):
    return load_settings(_env_file=None, **{**VALID, **overrides})


def test_valid_settings_load_and_hide_secrets():
    settings = make()
    assert settings.game_data_db_password.get_secret_value() == SECRET
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings.model_dump())


@pytest.mark.parametrize(
    ("app_env", "expected_db"),
    [("development", "operation_zero_dev"), ("test", "operation_zero_test"), ("production", "operation_zero")],
)
def test_app_env_selects_the_database(app_env, expected_db):
    assert make(app_env=app_env).mongodb_db_name == expected_db


def test_only_the_selected_environments_database_is_required():
    settings = make(app_env="production", mongodb_db_name_dev=None, mongodb_db_name_test=None)
    assert settings.mongodb_db_name == "operation_zero"


def test_selected_environments_database_must_be_set():
    with pytest.raises(ConfigError, match="MONGODB_DB_NAME_TEST is required when APP_ENV=test"):
        make(app_env="test", mongodb_db_name_test=None)


def test_test_database_must_end_with_test_suffix():
    with pytest.raises(ConfigError, match="MONGODB_DB_NAME_TEST must end with '_test'"):
        make(mongodb_db_name_test="operation_zero_scratch")


def test_database_names_must_all_differ():
    with pytest.raises(ConfigError, match="must all be different"):
        make(mongodb_db_name_dev="operation_zero_test", mongodb_db_name_test="operation_zero_test")


def test_uri_with_embedded_credentials_is_rejected_without_leaking_it():
    with pytest.raises(ConfigError) as exc_info:
        make(mongodb_uri=f"mongodb+srv://game_user:{SECRET}@cluster0.example.mongodb.net/")
    message = str(exc_info.value)
    assert "MONGODB_URI" in message
    assert "credentials" in message
    assert SECRET not in message
    assert exc_info.value.__cause__ is None and exc_info.value.__suppress_context__


def test_uri_with_wrong_scheme_is_rejected():
    with pytest.raises(ConfigError, match="MONGODB_URI"):
        make(mongodb_uri="https://cluster0.example.mongodb.net/")


def test_empty_password_is_rejected():
    with pytest.raises(ConfigError, match="GAME_DATA_DB_PASSWORD"):
        make(game_data_db_password="")


def test_short_jwt_secret_is_rejected_without_leaking_it():
    with pytest.raises(ConfigError, match="JWT_SECRET: Value error, must be at least 32 characters") as exc_info:
        make(jwt_secret="too-short-secret")
    assert "too-short-secret" not in str(exc_info.value)


def test_missing_settings_are_reported_by_env_name():
    with pytest.raises(ConfigError) as exc_info:
        load_settings(_env_file=None)
    message = str(exc_info.value)
    for name in ("MONGODB_URI", "GAME_DATA_DB_USER", "GAME_DATA_DB_PASSWORD", "JWT_SECRET"):
        assert name in message
