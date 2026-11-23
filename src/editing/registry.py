"""registry.py — single source of truth for every editing operation.

Each operation registers: a pure function (in_path, params, ctx) ->
out_path, plus metadata (stage, label, help, parameter schema, phase).
The Streamlit UI renders all toggles/sliders FROM this registry, so
adding an operation never requires UI surgery.

Parameter schema entries: {key, type: bool|float|int|select|text,
default, label, help, min, max, step, choices}.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Fixed pipeline stage order (MASTER-PROMPT-VIDEO-EDITING.md §1).
# Transitions sit in the "trim" stage group: they are an assembly
# operation applied right after segment extraction/trimming.
STAGE_ORDER = ["trim", "framing", "grade", "overlays", "captions",
               "audio", "loudnorm"]


@dataclass
class Operation:
    id: str
    stage: str                       # one of STAGE_ORDER
    label: str
    help: str
    phase: str                       # "A" or "B"
    func: Callable[[Path, dict, dict], Path]
    params: list[dict] = field(default_factory=list)

    def defaults(self) -> dict:
        return {p["key"]: p["default"] for p in self.params}


REGISTRY: dict[str, Operation] = {}


def register(op: Operation) -> Operation:
    if op.stage not in STAGE_ORDER:
        raise ValueError(f"Unknown stage {op.stage!r} for op {op.id!r}")
    REGISTRY[op.id] = op
    return op


def get(op_id: str) -> Operation:
    return REGISTRY[op_id]


def ordered_ops() -> list[Operation]:
    """All registered operations in fixed pipeline order."""
    return sorted(REGISTRY.values(),
                  key=lambda o: (STAGE_ORDER.index(o.stage), o.id))


def default_config() -> dict:
    """{op_id: {"enabled": False, "params": {...defaults}}} for all ops."""
    return {op.id: {"enabled": False, "params": op.defaults()}
            for op in REGISTRY.values()}


def load_operations() -> None:
    """Import every operation module so registration happens.
    Idempotent — safe to call more than once."""
    from . import trim, framing, grade, captions, audio, transitions  # noqa: F401
