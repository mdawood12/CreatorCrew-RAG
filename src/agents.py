"""
agents.py — LangGraph multi-agent team [Phase 4].

Patterns combined (per the master prompt):
- Supervisor/Router: the graph routes writer <-> critic until pass/max.
- ReAct tool use: the Researcher node calls the RAG retrieval tools.
- Bounded reflection: Critic loop with MAX_REVISIONS = 2 (config) —
  it can never loop forever, and it never silently passes a violation.

Agents: Planner -> Researcher -> Scriptwriter -> Critic -> (revise|END)
All LLM access goes through config.get_llm / call_llm_with_failover, so
the key pool [C15] and provider can change without touching this file.
Short-term memory: LangGraph MemorySaver checkpointer per thread_id.
"""
from __future__ import annotations

import json
import re
from typing import TypedDict

from . import config, memory, tools
from .config import logger
from .schemas import CriticReport, ScriptPackage

OVERLAP_LIMIT = 25.0  # % — above this the draft is sent back [C13]


def ngram_overlap(draft: str, source: str, n: int = 8) -> float:
    """% of the draft's word n-grams that also appear in the source."""
    def grams(text: str) -> set[tuple]:
        words = re.findall(r"[a-z0-9']+", text.lower())
        return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
    d, s = grams(draft), grams(source)
    if not d:
        return 0.0
    return round(100.0 * len(d & s) / len(d), 2)


class StudioState(TypedDict, total=False):
    topic: str
    profile: dict
    plan: str
    research_context: str
    policy_context: str
    citations: list
    draft: dict
    critic: dict
    feedback: str
    revisions: int
    source_text: str


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def planner_node(state: StudioState) -> StudioState:
    profile = state.get("profile") or memory.get_profile()
    prompt = (
        "You are the Planner/Strategist of a content studio.\n"
        f"Creator profile: {json.dumps(profile)}\n"
        f"Topic: {state['topic']}\n"
        "Write a short content plan (angle, hook direction, structure) "
        "for BOTH a YouTube video and a Facebook Reel on this topic. "
        "Plain text, under 150 words.")

    def _call(llm):
        return llm.invoke(prompt).content
    plan = config.call_llm_with_failover(_call)
    return {"plan": plan, "profile": profile, "revisions": 0}


def researcher_node(state: StudioState) -> StudioState:
    viral = tools.retrieve(state["topic"], doc_type="viral_transcript")
    policy = tools.retrieve(
        f"{state['topic']} monetization copyright reused content rules",
        doc_type="platform_policy")
    v_ctx, v_cites = tools.format_context(viral)
    p_ctx, p_cites = tools.format_context(policy)
    return {"research_context": v_ctx, "policy_context": p_ctx,
            "citations": sorted(set(v_cites + p_cites))}


def writer_node(state: StudioState) -> StudioState:
    feedback = state.get("feedback", "")
    prompt = (
        "You are the Scriptwriter of a content studio. Using the plan and "
        "the research context, write the complete content package.\n"
        f"TOPIC: {state['topic']}\nPLAN:\n{state.get('plan', '')}\n\n"
        f"RESEARCH (viral hooks/structures):\n{state.get('research_context', '')}\n\n"
        + (f"CRITIC FEEDBACK — fix these problems from the last draft:\n{feedback}\n\n"
           if feedback else "")
        + "Rules: 100% your own words; hook in the first 3 seconds; one clear "
          "CTA; follow platform policy. Return the package in the required "
          "structured format.")

    def _call(llm):
        try:
            structured = llm.with_structured_output(ScriptPackage)
            pkg = structured.invoke(prompt)
            return pkg.model_dump()
        except Exception as e:
            logger.warning("Structured output failed (%s) — JSON fallback", e)
            raw = llm.invoke(prompt + "\nReturn ONLY valid JSON matching the "
                             "ScriptPackage schema.").content
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
            data.setdefault("topic", state["topic"])
            return ScriptPackage(**data).model_dump()

    draft = config.call_llm_with_failover(_call)
    draft["citations"] = state.get("citations", [])
    return {"draft": draft}


def critic_node(state: StudioState) -> StudioState:
    draft = state["draft"]
    draft_text = json.dumps(draft, ensure_ascii=False)
    overlap = ngram_overlap(draft_text, state.get("source_text", "")) \
        if state.get("source_text") else 0.0
    prompt = (
        "You are the Critic / Compliance & Originality auditor.\n"
        "Audit this draft against the platform policy context.\n"
        f"POLICY CONTEXT:\n{state.get('policy_context', '')}\n\n"
        f"DRAFT:\n{draft_text}\n\n"
        f"Measured source-overlap: {overlap}% (limit {OVERLAP_LIMIT}%).\n"
        "Judge: (1) compliance with monetization/copyright/reused-content "
        "rules, (2) groundedness in the research (0-1), (3) originality. "
        "Return the CriticReport in the required structured format. "
        "verdict='revise' if compliance fails OR groundedness < 0.5.")

    def _call(llm):
        try:
            structured = llm.with_structured_output(CriticReport)
            rep = structured.invoke(prompt)
            return rep.model_dump()
        except Exception as e:
            # Fail CLOSED on compliance [Phase 0]: an unparseable Critic
            # audit must never silently approve a package. The package is
            # marked "needs review" (compliance_ok False, verdict revise)
            # and a human decides — the old fallback passed everything.
            logger.warning("Critic structured output failed (%s) — "
                           "failing CLOSED (needs review)", e)
            return {"compliance_ok": False,
                    "originality_overlap_pct": overlap,
                    "groundedness": 0.0,
                    "issues": ["NEEDS REVIEW: the Critic could not produce "
                               "a structured audit, so this package was "
                               "NOT approved automatically."],
                    "verdict": "revise"}

    report = config.call_llm_with_failover(_call)
    report["originality_overlap_pct"] = max(
        float(report.get("originality_overlap_pct", 0)), overlap)
    if overlap > OVERLAP_LIMIT:
        report["compliance_ok"] = False
        report["issues"] = list(report.get("issues", [])) + [
            f"Originality overlap {overlap}% exceeds {OVERLAP_LIMIT}% limit"]
    if not report["compliance_ok"] or report["originality_overlap_pct"] > OVERLAP_LIMIT:
        report["verdict"] = "revise"
    feedback = "; ".join(report.get("issues", []))
    return {"critic": report, "feedback": feedback,
            "revisions": state.get("revisions", 0) + (1 if report["verdict"] == "revise" else 0)}


def _route_after_critic(state: StudioState) -> str:
    critic = state.get("critic", {})
    if critic.get("verdict") == "revise" and \
            state.get("revisions", 0) < config.MAX_REVISIONS:
        return "writer"
    return "end"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph():
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    g = StateGraph(StudioState)
    g.add_node("planner", planner_node)
    g.add_node("researcher", researcher_node)
    g.add_node("writer", writer_node)
    g.add_node("critic", critic_node)
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_edge("researcher", "writer")
    g.add_edge("writer", "critic")
    g.add_conditional_edges("critic", _route_after_critic,
                            {"writer": "writer", "end": END})
    return g.compile(checkpointer=MemorySaver())


_GRAPH = None


def run_content_studio(topic: str, thread_id: str = "default",
                       source_text: str = "") -> dict:
    """Run the full team for a topic. Returns {draft, critic, citations}."""
    global _GRAPH
    if config.get_llm() is None:
        raise RuntimeError("No API key configured (demo mode). "
                           "Add GOOGLE_API_KEYS to .env to run the agents.")
    if _GRAPH is None:
        _GRAPH = build_graph()
    result = _GRAPH.invoke(
        {"topic": topic, "source_text": source_text,
         "profile": memory.get_profile()},
        config={"configurable": {"thread_id": thread_id}})
    draft, critic = result["draft"], result["critic"]
    memory.save_output("script", topic, "youtube+facebook", draft, critic)
    return {"draft": draft, "critic": critic,
            "citations": result.get("citations", [])}
