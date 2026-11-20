"""
schemas.py — Strict Pydantic v2 data contracts [Phase 3].

Every agent hand-off goes through one of these models, so a malformed
LLM output fails loudly at the boundary instead of corrupting the app.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class YouTubePackage(BaseModel):
    hook: str = Field(description="First-3-seconds hook line")
    retention_body: str = Field(description="Main script body, retention-paced")
    cta: str = Field(description="Call to action line")
    seo_title: str
    description: str
    tags: list[str] = Field(default_factory=list)


class FacebookPackage(BaseModel):
    reel_hook: str = Field(description="Short-form/Reel opening hook")
    pacing_notes: str = Field(description="Cut/pacing plan for the Reel")
    caption: str = Field(description="Engaging post caption with a CTA question")


class ScriptPackage(BaseModel):
    topic: str
    youtube: YouTubePackage
    facebook: FacebookPackage
    citations: list[str] = Field(
        default_factory=list,
        description="Sources from the knowledge base that grounded this script")


class CriticReport(BaseModel):
    compliance_ok: bool
    originality_overlap_pct: float = Field(
        ge=0, le=100, description="N-gram overlap with the source text [C13]")
    groundedness: float = Field(ge=0, le=1, description="0-1 groundedness score")
    issues: list[str] = Field(default_factory=list)
    verdict: Literal["pass", "revise"] = "pass"

    @field_validator("originality_overlap_pct")
    @classmethod
    def _round(cls, v: float) -> float:
        return round(float(v), 2)


class ClipCandidate(BaseModel):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    hook: str
    reason: str

    @field_validator("end_sec")
    @classmethod
    def _after_start(cls, v: float, info) -> float:
        start = info.data.get("start_sec", 0)
        if v <= start:
            raise ValueError("end_sec must be greater than start_sec")
        return v

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


class TransformResult(BaseModel):
    source_url: str
    source_ideas: list[str]
    angle: str
    original_script: str
    overlap_pct: float = Field(ge=0, le=100)


class EvalScore(BaseModel):
    question: str
    faithfulness: float = Field(ge=0, le=1)
    compliance: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    notes: str = ""
