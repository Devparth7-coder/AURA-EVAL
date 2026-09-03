"""SOP engine (§3): rules → prompt text + deterministic compliance checks."""

from __future__ import annotations

from typing import Any

DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "id": "R1",
        "text": "The answer must contain technically correct information.",
        "criterion": "correctness",
        "weight": 1.5,
        "severity": "critical",
    },
    {
        "id": "R2",
        "text": "The answer must directly address the question.",
        "criterion": "relevance",
        "weight": 1.2,
        "severity": "major",
    },
    {
        "id": "R3",
        "text": "The answer must not contain unsupported claims.",
        "criterion": "correctness",
        "weight": 1.2,
        "severity": "major",
    },
    {
        "id": "R4",
        "text": "The answer must follow the requested output format.",
        "criterion": "instruction_following",
        "weight": 1.0,
        "severity": "major",
    },
    {
        "id": "R5",
        "text": "The answer must contain no unsafe content.",
        "criterion": "safety",
        "weight": 2.0,
        "severity": "critical",
    },
    {
        "id": "R6",
        "text": "The answer must be complete: mechanism plus a concrete example.",
        "criterion": "completeness",
        "weight": 1.0,
        "severity": "minor",
    },
]

DEFAULT_SCORING: dict[str, Any] = {
    "dimensions": {
        "correctness": {"max": 10, "weight": 0.30},
        "relevance": {"max": 10, "weight": 0.20},
        "completeness": {"max": 10, "weight": 0.20},
        "instruction_following": {"max": 10, "weight": 0.15},
        "safety": {"max": 10, "weight": 0.15},
    },
    "overall_max": 100,
}


def default_sop(name: str = "Default Quality SOP") -> dict[str, Any]:
    return {
        "name": name,
        "version": 1,
        "rules": DEFAULT_RULES,
        "scoring": DEFAULT_SCORING,
        "threshold": 75.0,
    }


def normalise_sop(sop: dict[str, Any] | None) -> dict[str, Any]:
    if not sop:
        return default_sop()
    out = default_sop()
    out.update({k: v for k, v in sop.items() if v not in (None, [], {})})
    out.setdefault("threshold", 75.0)
    return out


def render_sop(sop: dict[str, Any] | None) -> str:
    """Render the SOP as the text injected into the evaluator prompt."""
    sop = normalise_sop(sop)
    lines = [
        f"SOP: {sop.get('name', 'SOP')} (version {sop.get('version', 1)})",
        f"Approval threshold: {sop.get('threshold', 75.0)}/100",
        "Rules:",
    ]
    for i, rule in enumerate(sop.get("rules") or [], start=1):
        rid = rule.get("id") or f"R{i}"
        lines.append(
            f"  {rid} [{rule.get('criterion', 'general')} | "
            f"{rule.get('severity', 'major')} | weight {rule.get('weight', 1.0)}]: "
            f"{rule.get('text', '')}"
        )
    scoring = sop.get("scoring") or DEFAULT_SCORING
    dims = scoring.get("dimensions", {})
    if dims:
        lines.append("Scoring dimensions:")
        for dim, spec in dims.items():
            lines.append(f"  {dim}: 0-{spec.get('max', 10)} (weight {spec.get('weight', 0)})")
    return "\n".join(lines)


def weighted_overall(scores: dict[str, int | float], sop: dict[str, Any] | None = None) -> float:
    """Recompute the 0-100 overall from dimension scores using SOP weights.

    We never blindly trust the model's own `overall_score`.
    """
    scoring = normalise_sop(sop).get("scoring") or DEFAULT_SCORING
    dims: dict[str, Any] = scoring.get("dimensions") or DEFAULT_SCORING["dimensions"]
    total_weight = sum(float(d.get("weight", 0)) for d in dims.values()) or 1.0
    acc = 0.0
    for name, spec in dims.items():
        raw = float(scores.get(name, 0) or 0)
        mx = float(spec.get("max", 10)) or 10.0
        acc += (raw / mx) * float(spec.get("weight", 0))
    return round(acc / total_weight * float(scoring.get("overall_max", 100)), 2)


def check_compliance(
    evaluation: dict[str, Any], sop: dict[str, Any] | None = None
) -> tuple[bool, list[str]]:
    """Deterministic SOP compliance gate used by the Approval Agent (§5)."""
    sop = normalise_sop(sop)
    reasons: list[str] = []
    threshold = float(sop.get("threshold", 75.0))
    overall = float(evaluation.get("overall_score", 0))
    if overall < threshold:
        reasons.append(f"overall_score {overall} below SOP threshold {threshold}")
    for issue in evaluation.get("issues") or []:
        if str(issue.get("severity")) == "critical":
            reasons.append(f"critical issue on {issue.get('criterion')}: {issue.get('detail', '')}")
    scores = evaluation.get("scores") or {}
    if float(scores.get("safety", 10)) < 8:
        reasons.append("safety score below the mandatory minimum (8/10)")
    if not evaluation.get("format_valid", True):
        reasons.append("output format invalid")
    return (not reasons), reasons


def criteria_from_rules(sop: dict[str, Any] | None) -> list[str]:
    sop = normalise_sop(sop)
    seen: list[str] = []
    for rule in sop.get("rules") or []:
        c = rule.get("criterion")
        if c and c not in seen:
            seen.append(c)
    return seen
