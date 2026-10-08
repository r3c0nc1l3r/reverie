"""The agent skills in skills/ stay installable with the skills CLI: skills/<name>/SKILL.md with YAML front
matter holding a lowercase-hyphen `name` equal to the folder name and a `description` that says when to use it."""

import re
from pathlib import Path

import pytest

SKILLS = sorted((Path(__file__).parent.parent / "skills").glob("*/SKILL.md"))


def front_matter(path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} has no front matter"
    fields = dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)
    return fields, text[match.end():]


def test_there_are_skills():
    assert len(SKILLS) >= 3


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_front_matter(path):
    fields, body = front_matter(path)
    assert fields.get("name") == path.parent.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"])
    description = fields.get("description", "")
    assert 80 <= len(description) <= 1024 and "Use when" in description
    assert body.strip().startswith("# ")


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skills_use_current_names(path):
    text = path.read_text()
    assert not re.search(r"LAYA_AGENT_[A-Z]", text), "use the REVERIE_* setting names"
    assert "laya-agent " not in text, "lead with the reverie command"
