"""The `heronry` command table (S15 s-6d5fdf783a): `help` prints it and the project site's CLI reference is
generated from it, so every dispatched command has a row and every row's flags are printed."""
from __future__ import annotations

from edp8 import cli, model_catalog


def test_every_command_has_a_row_and_every_row_dispatches():
    rows = {c.name for c in cli.COMMANDS}
    assert rows == set(cli._COMMANDS)
    assert len(rows) == len(cli.COMMANDS)  # no duplicates


def test_help_prints_every_usage_and_flag(capsys):
    cli.help_cmd([])
    out = capsys.readouterr().out
    for c in cli.COMMANDS:
        assert c.usage in out and c.summary in out
        for flag, text in c.flags:
            assert f"{flag}  {text}" in out


def test_model_fields_are_the_documented_fields():
    assert model_catalog.MODEL_FIELDS == set(model_catalog.MODEL_FIELD_DOCS)
    assert all(v.strip() for v in model_catalog.MODEL_FIELD_DOCS.values())
    assert set(model_catalog.CATALOG_KEY_DOCS) == {"models", "role_models", "default_model"}
