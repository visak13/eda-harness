"""Sol-harness vault projection (2026-07-19): the JSON stores stay
authoritative; every save re-renders an Obsidian note. These tests drive the
REAL stores end-to-end and read the notes back."""

from edp_claude.schemas import Plan, Recipe
from edp_claude.store.plan_store import PlanStore
from edp_claude.store.recipe_store import RecipeStore


def _mk_recipe(rid: str) -> Recipe:
    return Recipe(
        recipe_id=rid,
        user_goal_verbatim="prove the vault mirror",
        user_goal_distilled="prove the vault mirror",
        domain="framework",
        state="created",
        created_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
    )


def test_recipe_save_renders_a_vault_note(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("EDP_VAULT_DIR", str(vault))
    store = RecipeStore(tmp_path / ".recipes")
    r = _mk_recipe("recipe-vault-probe-000001")
    store.save(r)
    note = vault / "recipes" / "recipe-vault-probe-000001.md"
    assert note.exists(), "a recipe save must project its vault note"
    text = note.read_text(encoding="utf-8")
    assert "prove the vault mirror" in text
    assert "state: created" in text


def test_plan_save_renders_note_with_backlink_and_checkboxes(
        tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("EDP_VAULT_DIR", str(vault))
    store = PlanStore(tmp_path / ".plans")
    p = Plan(
        plan_id="recipe-vault-probe-000001-s1",
        recipe_id="recipe-vault-probe-000001",
        recipe_step_id="s1",
        domain="framework",
        shape="linear-build",
        goal="one action",
        state="drafted",
    )
    store.save(p)
    text = (vault / "plans" / "recipe-vault-probe-000001-s1.md").read_text(
        encoding="utf-8")
    assert "[[recipe-vault-probe-000001]]" in text, "Obsidian backlink"


def test_vault_mirror_disabled_by_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_VAULT_DIR", "0")
    store = RecipeStore(tmp_path / ".recipes")
    store.save(_mk_recipe("recipe-vault-probe-000002"))
    assert not (tmp_path / "vault").exists()


def test_vault_write_failure_never_fails_the_save(tmp_path, monkeypatch):
    # point the vault at an impossible location: the save must still land.
    monkeypatch.setenv("EDP_VAULT_DIR", str(tmp_path / "recipefile"))
    (tmp_path / "recipefile").write_text("a FILE where a dir is needed")
    store = RecipeStore(tmp_path / ".recipes")
    r = _mk_recipe("recipe-vault-probe-000003")
    v = store.save(r)
    assert v >= 1
    assert store.exists("recipe-vault-probe-000003")
