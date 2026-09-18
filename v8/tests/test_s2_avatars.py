"""S2 runtime delivery matches approved templates without changing human selection semantics."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from edp8 import avatars
from edp8.avatar_templates import BOT_TEMPLATES

FINAL = Path(__file__).resolve().parents[1] / "docs/ui-redesign-concepts/s1-assets/final"


def test_human_source_preserved():
    expected = json.loads((FINAL / "human-preservation.json").read_text())
    found = {}
    for node in ast.parse(Path(avatars.__file__).read_text(encoding="utf-8")).body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.Assign):
            name = getattr(node.targets[0], "id", None)
        if name in expected:
            found[name] = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    assert found == expected


def test_templates_and_dispatch():
    assert BOT_TEMPLATES == json.loads((FINAL / "bot-templates.json").read_text())
    for role, template in BOT_TEMPLATES.items():
        result = avatars.role_avatar_svg(role, size=24)
        assert template["body"] in result
        assert ET.fromstring(result).attrib["width"] == "24"
    assert avatars.role_avatar_svg("engineer", "gpt-6-astra") == avatars.role_avatar_svg("consultant")
    assert avatars.role_avatar_svg("not-a-role") == avatars.system_avatar_svg(unknown=True)
    for avatar_id in avatars.HUMAN_AVATAR_IDS:
        human = SimpleNamespace(type="human", role="consultant", model="gpt", avatar_id=avatar_id)
        assert avatars.avatar_svg(human) == avatars.human_avatar_svg(avatar_id)
