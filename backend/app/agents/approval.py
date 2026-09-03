"""Approval / Quality Agent (§5). Fully deterministic — no LLM call."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from app.agents.base import Agent
from app.schemas.agents import ApprovalReport, GeneratedSample
from app.services.sop_engine import check_compliance, normalise_sop

REQUIRED_FIELDS = ("input", "response")


def content_hash(payload: dict[str, Any]) -> str:
    basis = f"{str(payload.get('input', '')).strip().lower()}"
    return hashlib.sha256(basis.encode()).hexdigest()


class ApprovalAgent(Agent):
    name = "approval"
    prompt_key = "approval"

    def run(
        self,
        *,
        sample: dict[str, Any],
        evaluation: dict[str, Any],
        seen_hashes: set[str],
        required_fields: list[str] | None = None,
    ) -> ApprovalReport:
        started = time.perf_counter()
        reasons: list[str] = []

        # 1. Schema validation
        schema_valid = True
        try:
            GeneratedSample.model_validate(
                {k: v for k, v in sample.items() if k not in ("sample_id", "metadata")}
            )
        except Exception as exc:
            schema_valid = False
            reasons.append(f"schema validation failed: {type(exc).__name__}")

        # 2. Required fields
        fields = list(required_fields or REQUIRED_FIELDS)
        missing = [f for f in fields if not str(sample.get(f, "")).strip()]
        required_ok = not missing
        if missing:
            reasons.append(f"missing required fields: {', '.join(missing)}")

        # 3. Duplicate detection
        h = content_hash(sample)
        duplicate = h in seen_hashes
        if duplicate:
            reasons.append("duplicate sample (identical input already approved)")

        # 4. Quality threshold
        sop = normalise_sop(self.ctx.sop)
        threshold = float(self.ctx.config.get("approval_threshold", sop.get("threshold", 75.0)))
        overall = float(evaluation.get("overall_score", 0))
        quality_ok = overall >= threshold
        if not quality_ok:
            reasons.append(f"quality {overall} below approval threshold {threshold}")

        # 5. Metadata validation
        meta = sample.get("metadata") or {}
        metadata_valid = bool(sample.get("sample_id")) and bool(meta.get("run_id"))
        if not metadata_valid:
            reasons.append("sample metadata incomplete (sample_id/run_id)")

        # 6. SOP compliance
        sop_ok, sop_reasons = check_compliance(evaluation, sop)
        reasons.extend(sop_reasons)

        report = ApprovalReport(
            approved=all(
                [schema_valid, required_ok, not duplicate, quality_ok, metadata_valid, sop_ok]
            ),
            schema_valid=schema_valid,
            required_fields_present=required_ok,
            duplicate=duplicate,
            quality_threshold_met=quality_ok,
            metadata_valid=metadata_valid,
            sop_compliant=sop_ok,
            reasons=reasons,
        )
        self.local_telemetry(
            status="SUCCESS" if report.approved else "DEGRADED",
            input_json={"sample_id": sample.get("sample_id"), "overall_score": overall},
            output_json=report.model_dump(mode="json"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            sample_key=sample.get("sample_id"),
            error_type=None if report.approved else "APPROVAL_REJECTED",
            error_message=None if report.approved else "; ".join(reasons)[:500],
        )
        return report
