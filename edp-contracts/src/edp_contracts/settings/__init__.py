"""edp_contracts.settings — the one settings registry for edp8, edp-pool, edp-broker and edp-contracts.

Every knob is declared once (key, env, type, default, group, secret, restart_required, doc) in the
``keys_*`` modules; resolution is env > config.toml > default. See ``_core`` for the rules.
"""
from __future__ import annotations

from . import keys_board as _keys_board  # noqa: F401
from . import keys_broker as _keys_broker  # noqa: F401
from . import keys_common as _keys_common  # noqa: F401  (declarations, shared first)
from . import keys_pool as _keys_pool  # noqa: F401
from . import keys_seats as _keys_seats  # noqa: F401
from ._core import (
    ADMIN_TOKEN_FILE,
    APP_DIR_NAME,
    REGISTRY,
    TYPES,
    Setting,
    SECRET_SETTINGS_FILE,
    TIERS,
    SettingsError,
    admin_token,
    admin_token_file,
    agent_home,
    all_settings,
    config_dir,
    config_file,
    config_values,
    data_dir,
    declare,
    dev_mode,
    env_raw,
    environ_copy,
    get,
    home,
    is_set,
    logs_dir,
    pop_env,
    resolve,
    run_dir,
    secret_settings_file,
    secret_values,
    secrets_dir,
    set_env,
    setting,
    source,
)

__all__ = [
    "APP_DIR_NAME", "REGISTRY", "TIERS", "TYPES", "Setting", "SettingsError",
    "ADMIN_TOKEN_FILE", "admin_token", "admin_token_file", "agent_home", "all_settings", "config_dir", "config_file", "config_values",
    "data_dir", "declare", "dev_mode", "env_raw", "environ_copy", "get", "home", "is_set", "logs_dir", "pop_env", "resolve",
    "run_dir", "SECRET_SETTINGS_FILE", "secret_settings_file", "secret_values", "secrets_dir", "set_env", "setting", "source",
]
