from __future__ import annotations

from collections.abc import Mapping


def validate_required_env(required_keys: list[str], env: Mapping[str, str]) -> None:
    missing = [key for key in required_keys if not env.get(key)]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing required environment variables: {missing_list}")
