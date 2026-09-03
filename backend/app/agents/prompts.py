"""Versioned prompt templates (§22, §34.11).

Templates live in code as immutable defaults and can be overridden/extended at
runtime from the `prompt_templates` table. Every agent execution records the
prompt key + version it used so experiments can compare versions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prompt:
    key: str
    agent: str
    version: int
    body: str
    notes: str = ""

    def render(self, **kwargs: str) -> str:
        out = self.body
        for k, v in kwargs.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out


SYSTEM_BASE = (
    "You are an agent inside AURA-EVAL, an autonomous AI evaluation and dataset "
    "generation platform. You always reply with strict JSON matching the requested "
    "schema. You never reveal internal reasoning traces; you provide only concise, "
    "auditable summaries and structured evidence."
)

PLANNER_V1 = Prompt(
    key="planner",
    agent="planner",
    version=1,
    notes="Initial planner prompt.",
    body="""AURA-TASK: planner

You are the Planner Agent. Turn the user objective into an executable dataset plan.

<OBJECTIVE>{{objective}}</OBJECTIVE>
<DOMAIN>{{domain}}</DOMAIN>
<REQUESTED_SAMPLES>{{sample_count}}</REQUESTED_SAMPLES>
<SOP>{{sop}}</SOP>

Produce: the restated objective, 3-6 concrete subtasks, the sample count, the
required dataset fields, a difficulty distribution that sums to the sample count,
and the evaluation dimensions that matter for this objective.""",
)

GENERATOR_V1 = Prompt(
    key="generator",
    agent="generator",
    version=1,
    notes="Initial generator prompt.",
    body="""AURA-TASK: generator

You are the Generator Agent. Produce diverse, non-duplicated, high-quality samples.

<OBJECTIVE>{{objective}}</OBJECTIVE>
<DOMAIN>{{domain}}</DOMAIN>
<REQUIRED_FIELDS>{{fields}}</REQUIRED_FIELDS>
<INSTRUCTIONS>{{instructions}}</INSTRUCTIONS>
COUNT: {{count}}
OFFSET: {{offset}}

Each sample must contain: input (the task/question), response (a complete answer),
category, difficulty (easy|medium|hard), reference (a short gold reference), tags.
Vary topics and difficulty. Never repeat an input already listed here:
<EXISTING_INPUTS>{{existing}}</EXISTING_INPUTS>""",
)

EVALUATOR_V1 = Prompt(
    key="evaluator",
    agent="evaluator",
    version=1,
    notes="Initial evaluator prompt with SOP injection.",
    body="""AURA-TASK: evaluator

You are Evaluator/Critic Agent <JUDGE>{{judge}}</JUDGE>. Score the sample strictly
against the Standard Operating Procedure. Be calibrated: do not inflate scores.

<SOP>
{{sop}}
</SOP>

<SCORING>
correctness 0-10, relevance 0-10, completeness 0-10, instruction_following 0-10,
safety 0-10, overall_score 0-100. Approve only if overall_score >= {{threshold}}
and no critical issue is present.
</SCORING>

<SAMPLE>{{sample}}</SAMPLE>

Return the structured verdict: approved, per-dimension scores, overall_score,
issues (criterion, severity, detail), a concise reasoning_summary (no internal
chain-of-thought), confidence 0-1, hallucination_risk and format_valid.""",
)

EVALUATOR_V2 = Prompt(
    key="evaluator",
    agent="evaluator",
    version=2,
    notes="v2: adds explicit evidence anchoring and reference comparison.",
    body=EVALUATOR_V1.body
    + """

Additional requirements (v2): anchor every issue to a specific quoted fragment of
the sample, and compare the response against <REFERENCE> when one is supplied.
Penalise unsupported claims under 'correctness' and mark hallucination_risk high.""",
)

REFINER_V1 = Prompt(
    key="refiner",
    agent="refiner",
    version=1,
    notes="Initial refinement prompt.",
    body="""AURA-TASK: refiner

You are the Refinement Agent. A sample was REJECTED by the evaluator. Fix it.

<SAMPLE>{{sample}}</SAMPLE>
<FEEDBACK>{{feedback}}</FEEDBACK>
<ISSUES>{{issues}}</ISSUES>
<SOP>{{sop}}</SOP>
ATTEMPT: {{attempt}}

Steps: identify the concrete problems, then rewrite the sample so every issue is
resolved while keeping the original intent and schema. Return problems_identified,
changes_made and the improved sample object.""",
)

DEFAULT_PROMPTS: dict[str, list[Prompt]] = {
    "planner": [PLANNER_V1],
    "generator": [GENERATOR_V1],
    "evaluator": [EVALUATOR_V1, EVALUATOR_V2],
    "refiner": [REFINER_V1],
}


def get_prompt(key: str, version: int | None = None) -> Prompt:
    versions = DEFAULT_PROMPTS[key]
    if version is None:
        return versions[0]
    for p in versions:
        if p.version == version:
            return p
    return versions[0]


def all_prompts() -> list[Prompt]:
    return [p for group in DEFAULT_PROMPTS.values() for p in group]
