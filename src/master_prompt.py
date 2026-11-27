"""
master_prompt.py — Master Prompt lock system [Step 1].

A template is set ONCE — recurring characters, visual style,
structure (format, beat count, hook, CTA) and posting defaults —
saved under a name, and locked. Step 2 (generation by topic only)
will read these templates; this module is storage + the small pure
helpers the UI needs, with all persistence delegated to memory.py.

Characters are edited as plain text, one per line:
    Name — description
(the parser also accepts "Name: description" and bare names).

Each template also owns a Topics section: topics are saved under
exactly one template (never mixed), carry a status
(new/generated/posted) and, once generation lands, their result.
"""
from __future__ import annotations

from . import memory
from .schemas import MasterPromptTemplate, MasterTopic

EM_DASH = "—"


def parse_characters(text: str) -> list[dict]:
    """Parse the characters text area into [{name, description}].

    One character per non-empty line. Split on the first "—" if the
    line has one, else on the first ":"; a line with no separator is
    a bare name with an empty description.
    """
    chars: list[dict] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if EM_DASH in line:
            name, _, desc = line.partition(EM_DASH)
        elif ":" in line:
            name, _, desc = line.partition(":")
        else:
            name, desc = line, ""
        chars.append({"name": name.strip(),
                      "description": desc.strip()})
    return chars


def format_characters(chars: list[dict]) -> str:
    """Render characters back to the one-per-line text format."""
    lines: list[str] = []
    for c in chars or []:
        if isinstance(c, dict):
            name = str(c.get("name", "")).strip()
            desc = str(c.get("description", "")).strip()
        else:  # a TemplateCharacter (or anything with the attributes)
            name = str(getattr(c, "name", "")).strip()
            desc = str(getattr(c, "description", "")).strip()
        if not name and not desc:
            continue
        lines.append(f"{name} {EM_DASH} {desc}" if desc else name)
    return "\n".join(lines)


def save(template: MasterPromptTemplate) -> MasterPromptTemplate:
    """Validate + persist a template; returns the stored template."""
    stored = memory.save_template(template.model_dump())
    return MasterPromptTemplate(**stored)


def load(name: str) -> MasterPromptTemplate | None:
    """Load a template by name, or None if it does not exist."""
    data = memory.get_template(name)
    return MasterPromptTemplate(**data) if data else None


def list_names() -> list[str]:
    return memory.list_template_names()


def delete(name: str) -> bool:
    """Delete a template AND all of its topics (they belong to it)."""
    memory.delete_topics_for_template(name)
    return memory.delete_template(name)


# ----------------------------------------------------------------------
# Topics — each template owns its own topics section [Topics Step 1].
# Generation (Step 2) will call save_topic_result() to auto-save a
# finished package onto the topic it was generated from.
# ----------------------------------------------------------------------
def add_topic(template_name: str, topic: str) -> MasterTopic:
    """Add a topic under a template; empty topics are rejected."""
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Topic cannot be empty.")
    stored = memory.add_topic(template_name, topic)
    return MasterTopic(**stored)


def list_topics(template_name: str) -> list[MasterTopic]:
    """The template's topics, latest first."""
    return [MasterTopic(**t) for t in memory.list_topics(template_name)]


def topic_exists(template_name: str, topic: str) -> bool:
    """Case-insensitive duplicate check within this template only."""
    return memory.find_topic(template_name, topic) is not None


def set_topic_status(topic_id: int, status: str) -> bool:
    return memory.set_topic_status(topic_id, status)


def save_topic_result(topic_id: int, result: dict) -> bool:
    return memory.save_topic_result(topic_id, result)


def delete_topic(topic_id: int) -> bool:
    return memory.delete_topic(topic_id)


def count_topics(template_name: str) -> int:
    return memory.count_topics(template_name)
