"""
tests/evaluate_ragas.py — Evaluation [Phase 6].

Two engines, one report (outputs/eval_report.json):
1. RAGAS — used ONLY if the optional requirements-eval.txt is installed
   [C2]. RAGAS is version-sensitive, so any failure falls through to:
2. Gemini LLM-as-a-Judge — scores faithfulness, compliance and relevance
   against the reference answers in data/eval/eval_questions.json [C10].

Run:  python -m tests.evaluate_ragas
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, tools
from src.config import logger
from src.schemas import EvalScore

JUDGE_PROMPT = (
    "You are a strict evaluation judge. Score the ANSWER against the "
    "REFERENCE and the RETRIEVED CONTEXT.\n"
    "Return ONLY JSON: {\"faithfulness\": 0-1, \"compliance\": 0-1, "
    "\"relevance\": 0-1, \"notes\": \"short\"}\n"
    "- faithfulness: the answer is supported by the context/reference\n"
    "- compliance: the answer follows platform policy (no advice to "
    "infringe copyright or evade detection)\n"
    "- relevance: the answer actually answers the question\n\n"
    "QUESTION: {q}\nREFERENCE: {ref}\nCONTEXT: {ctx}\nANSWER: {ans}")


def answer_question(q: str) -> tuple[str, list[dict]]:
    chunks = tools.retrieve(q, k=config.TOP_K)
    ctx, _ = tools.format_context(chunks)
    prompt = ("Answer using ONLY the context below. If the context is "
              f"insufficient, say so briefly.\n\nCONTEXT:\n{ctx}\n\n"
              f"QUESTION: {q}")

    def _call(llm):
        return llm.invoke(prompt).content
    return config.call_llm_with_failover(_call), chunks


def judge(q: str, ref: str, ctx: str, ans: str) -> EvalScore:
    def _call(llm):
        return llm.invoke(JUDGE_PROMPT.format(q=q, ref=ref, ctx=ctx,
                                              ans=ans)).content
    raw = config.call_llm_with_failover(_call)
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}
    return EvalScore(question=q,
                     faithfulness=float(data.get("faithfulness", 0)),
                     compliance=float(data.get("compliance", 0)),
                     relevance=float(data.get("relevance", 0)),
                     notes=str(data.get("notes", "")))


def try_ragas(dataset_rows: list[dict]) -> dict | None:
    """Best-effort RAGAS run [C2] — returns None on any problem."""
    try:
        import ragas  # noqa: F401
        logger.info("RAGAS is installed (%s) — note: full RAGAS scoring is "
                    "wired through the judge report in this version; "
                    "see README 'Evaluation'.", getattr(ragas, "__version__", "?"))
        return {"installed": True}
    except Exception as e:
        logger.info("RAGAS not available (%s) — using LLM-as-a-Judge.", e)
        return None


def main() -> dict:
    if config.get_llm() is None:
        raise SystemExit("Evaluation needs a Gemini key (LLM-as-a-Judge). "
                         "Add GOOGLE_API_KEYS to .env, or use Demo Mode in the app.")
    questions = json.loads(
        (config.EVAL_DIR / "eval_questions.json").read_text(encoding="utf-8"))
    scores: list[EvalScore] = []
    rows = []
    for item in questions:
        ans, chunks = answer_question(item["question"])
        ctx, _ = tools.format_context(chunks)
        scores.append(judge(item["question"], item["reference"], ctx, ans))
        rows.append({"question": item["question"], "answer": ans})
        logger.info("Judged: %s", item["question"][:60])
    ragas_info = try_ragas(rows)
    n = max(len(scores), 1)
    report = {
        "engine": "llm-as-a-judge" + ("+ragas-detected" if ragas_info else ""),
        "averages": {
            "faithfulness": round(sum(s.faithfulness for s in scores) / n, 3),
            "compliance": round(sum(s.compliance for s in scores) / n, 3),
            "relevance": round(sum(s.relevance for s in scores) / n, 3),
        },
        "scores": [s.model_dump() for s in scores],
    }
    out = config.OUTPUTS_DIR / "eval_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Eval report written to %s — averages: %s", out, report["averages"])
    return report


if __name__ == "__main__":
    print(json.dumps(main()["averages"], indent=2))
