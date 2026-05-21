import pytest

from orchestration.config import validate_required_env


def test_validate_required_env_passes_when_all_present() -> None:
    env = {
        "SUPABASE_DB_HOST": "host",
        "SUPABASE_DB_PORT": "6543",
        "SUPABASE_DB_NAME": "postgres",
    }
    validate_required_env(
        ["SUPABASE_DB_HOST", "SUPABASE_DB_PORT", "SUPABASE_DB_NAME"], env=env
    )


def test_validate_required_env_raises_for_missing_values() -> None:
    env = {"SUPABASE_DB_HOST": "host", "SUPABASE_DB_PORT": ""}
    with pytest.raises(ValueError) as exc:
        validate_required_env(
            ["SUPABASE_DB_HOST", "SUPABASE_DB_PORT", "SUPABASE_DB_NAME"], env=env
        )
    assert "SUPABASE_DB_NAME" in str(exc.value)
    assert "SUPABASE_DB_PORT" in str(exc.value)
