"""Resumable, serverless-safe workflow executor (§39, §40).

The LangGraph topology in `graph.py` is the source of truth for the state machine.
`StepExecutor` walks that same topology **one node at a time**, persisting the full
`EvaluationState` to `workflow_runs.state` after every node. That is what makes a
run resumable across serverless invocation boundaries: any invocation may die and
the next `advance()` continues exactly where it stopped.

`run_to_completion` = repeated bounded slices, so the same code path serves the
local background task, a Redis worker and a Vercel cron tick.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentTelemetry
from app.core.config import settings
from app.core.errors import AuraError, WorkflowExecutionError
from app.core.logging import get_logger, run_id_ctx
from app.models import (
    AgentRun,
    Evaluation,
    Sample,
    SampleVersion,
    WorkflowEvent,
    WorkflowRun,
)
from app.models.enums import EventType, RunStatus
from app.workflows.graph import NODES, route_critic, route_dispatch, route_refiner
from app.workflows.nodes import Runtime, register_runtime, unregister_runtime
from app.workflows.state import EvaluationState, new_state

log = get_logger(__name__)

TERMINAL_NODES = {"done"}


def _now() -> datetime:
    return datetime.now(UTC)


class StepExecutor:
    """Executes a workflow run in bounded slices with durable checkpoints."""

    def __init__(self, db: Session, run: WorkflowRun) -> None:
        self.db = db
        self.run = run
        self._seq = self._next_seq()
        self._sample_cache: dict[str, Sample] = {}

    # -- persistence helpers --------------------------------------------
    def _next_seq(self) -> int:
        last = self.db.execute(
            select(WorkflowEvent.seq)
            .where(WorkflowEvent.run_id == self.run.id)
            .order_by(WorkflowEvent.seq.desc())
            .limit(1)
        ).scalar()
        return int(last or 0)

    def emit(self, etype: str, message: str, data: dict[str, Any] | None = None) -> None:
        self._seq += 1
        level = "error" if "fail" in etype else ("warn" if "review" in etype else "info")
        self.db.add(
            WorkflowEvent(
                run_id=self.run.id,
                seq=self._seq,
                type=str(etype),
                level=level,
                message=message[:1000],
                data=data or {},
                created_at=_now(),
            )
        )

    def record(self, tel: AgentTelemetry) -> None:
        sample_pk = None
        if tel.sample_key:
            s = self._get_sample(tel.sample_key)
            sample_pk = s.id if s else None
        self.db.add(
            AgentRun(
                id=uuid.UUID(tel.id),
                run_id=self.run.id,
                sample_id=sample_pk,
                agent=tel.agent,
                status=tel.status,
                attempt=tel.attempt,
                provider=tel.provider,
                model=tel.model,
                prompt_key=tel.prompt_key,
                prompt_version=tel.prompt_version,
                input_json=tel.input_json,
                output_json=tel.output_json,
                latency_ms=tel.latency_ms,
                input_tokens=tel.input_tokens,
                output_tokens=tel.output_tokens,
                cost_usd=tel.cost_usd,
                error_type=tel.error_type,
                error_message=tel.error_message,
            )
        )

    def _get_sample(self, key: str) -> Sample | None:
        if key in self._sample_cache:
            return self._sample_cache[key]
        s = self.db.execute(
            select(Sample).where(Sample.run_id == self.run.id, Sample.sample_key == key)
        ).scalar_one_or_none()
        if s:
            self._sample_cache[key] = s
        return s

    def sample_sink(
        self,
        payload: dict[str, Any],
        status: str,
        *,
        approval: dict[str, Any] | None = None,
        score: float | None = None,
        reason: str | None = None,
        version_source: str = "generator",
        feedback: str = "",
    ) -> None:
        from app.agents import content_hash

        key = str(payload.get("sample_id"))
        sample = self._get_sample(key)
        if sample is None:
            sample = Sample(
                run_id=self.run.id,
                sample_key=key,
                payload=payload,
                content_hash=content_hash(payload),
                status=status,
            )
            self.db.add(sample)
            self.db.flush()
            self._sample_cache[key] = sample
            self.db.add(
                SampleVersion(
                    sample_id=sample.id,
                    version=1,
                    payload=payload,
                    source="generator",
                    outcome="pending",
                )
            )
        else:
            sample.payload = payload
            sample.status = status
            sample.content_hash = content_hash(payload)
            if version_source != "generator":
                current_max = (
                    self.db.execute(
                        select(SampleVersion.version)
                        .where(SampleVersion.sample_id == sample.id)
                        .order_by(SampleVersion.version.desc())
                        .limit(1)
                    ).scalar()
                    or 1
                )
                nxt = int(current_max) + 1
                sample.retry_count = max(sample.retry_count, nxt - 1)
                self.db.add(
                    SampleVersion(
                        sample_id=sample.id,
                        version=nxt,
                        payload=payload,
                        source=version_source,
                        feedback_applied=feedback,
                        outcome="pending",
                    )
                )
        if approval is not None:
            sample.approval_report = approval
        if score is not None:
            sample.final_score = float(score)
        if reason:
            sample.failure_reason = reason[:1000]
        self.db.flush()

    def _persist_evaluation(self, state: EvaluationState) -> None:
        ev = state.get("evaluation")
        if not ev:
            return
        key = str(ev.get("sample_id") or "")
        sample = self._get_sample(key)
        if sample is None:
            return
        attempt = int(ev.get("attempt", 1))
        exists = any(
            e.attempt == attempt and e.judge_label == "consensus" for e in sample.evaluations
        )
        if exists:
            return
        consensus = state.get("consensus") or {}
        for verdict in ev.get("judges") or []:
            r = verdict.get("result", {})
            self.db.add(
                Evaluation(
                    sample_id=sample.id,
                    run_id=self.run.id,
                    attempt=attempt,
                    judge_label=f"judge_{verdict.get('judge', '?')}",
                    approved=bool(r.get("approved")),
                    scores=r.get("scores", {}),
                    overall_score=float(r.get("overall_score", 0)),
                    issues=r.get("issues", []),
                    reasoning_summary=str(r.get("reasoning_summary", ""))[:2000],
                    confidence=float(r.get("confidence", 0)),
                    hallucination_risk=str(r.get("hallucination_risk", "low")),
                    is_consensus=False,
                    sop_version=int((state.get("sop") or {}).get("version", 1)),
                )
            )
        self.db.add(
            Evaluation(
                sample_id=sample.id,
                run_id=self.run.id,
                attempt=attempt,
                judge_label="consensus",
                approved=bool(ev.get("approved")),
                scores=ev.get("scores", {}),
                overall_score=float(ev.get("overall_score", 0)),
                issues=ev.get("issues", []),
                reasoning_summary=str(ev.get("reasoning_summary", ""))[:2000],
                confidence=float(ev.get("confidence", 0)),
                hallucination_risk=str(ev.get("hallucination_risk", "low")),
                is_consensus=True,
                variance=float(consensus.get("variance", 0)),
                agreement_rate=float(consensus.get("agreement_rate", 1.0)),
                sop_version=int((state.get("sop") or {}).get("version", 1)),
            )
        )
        # Attach the outcome to the *version that was judged* (attempt N ↔ version N),
        # not to whatever version happens to be latest.
        versions = list(
            self.db.execute(
                select(SampleVersion)
                .where(SampleVersion.sample_id == sample.id)
                .order_by(SampleVersion.version)
            ).scalars()
        )
        target = next((v for v in versions if v.version == attempt), None)
        if target is None and versions:
            target = versions[-1]
        if target is not None:
            target.outcome = "approved" if ev.get("approved") else "rejected"
        self.db.flush()

    def _sync_counters(self, state: EvaluationState) -> None:
        meta = state.get("execution_metadata") or {}
        self.run.state = dict(state)
        self.run.plan = dict(state.get("plan") or {})
        self.run.steps_executed = int(meta.get("steps", 0))
        self.run.samples_generated = len(state.get("generated_samples") or [])
        self.run.samples_approved = len(state.get("approved_samples") or [])
        self.run.samples_rejected = len(state.get("rejected_samples") or [])
        self.run.samples_failed = len(state.get("failed_samples") or [])
        self.run.samples_review = len(state.get("review_samples") or [])
        self.run.total_input_tokens = int(meta.get("input_tokens", 0))
        self.run.total_output_tokens = int(meta.get("output_tokens", 0))
        self.run.total_cost_usd = float(meta.get("cost_usd", 0.0))

    # -- routing ---------------------------------------------------------
    @staticmethod
    def _next_node(node: str, state: EvaluationState) -> str:
        if node == "planner":
            return "generator"
        if node == "generator":
            return "dispatch"
        if node == "dispatch":
            return route_dispatch(state)
        if node == "critic":
            return route_critic(state)
        if node == "refiner":
            return route_refiner(state)
        if node in ("approval", "human_gate", "fail_sample"):
            return "dispatch"
        if node == "dataset_builder":
            return "export"
        return "done"

    # -- execution -------------------------------------------------------
    async def advance(self, max_steps: int | None = None) -> EvaluationState:
        """Execute at most `max_steps` graph nodes, then checkpoint and return."""
        max_steps = max_steps or settings.default_slice_steps
        state: EvaluationState = dict(self.run.state or {})  # type: ignore[assignment]
        if not state:
            raise WorkflowExecutionError("run has no state; call `start` first")

        run_id_ctx.set(str(self.run.id))
        register_runtime(str(self.run.id), Runtime(self.emit, self.record, self.sample_sink))
        node = str(state.get("resume_at") or "planner")
        executed = 0
        try:
            while executed < max_steps and node not in TERMINAL_NODES:
                self.db.refresh(self.run, ["stop_requested"])
                if self.run.stop_requested:
                    state["stop_requested"] = True
                    self.emit(EventType.RUN_STOPPED, "Stop requested — finalising run", {})
                    node = "dataset_builder" if state.get("approved_samples") else "done"
                    if node == "done":
                        self.run.status = RunStatus.STOPPED
                        self.run.finished_at = _now()
                        break

                fn = NODES[node]
                try:
                    partial = await fn(state)  # type: ignore[operator]
                except AuraError as exc:
                    return self._fail(state, node, exc)
                except Exception as exc:
                    return self._fail(
                        state, node, WorkflowExecutionError(f"{type(exc).__name__}: {exc}")
                    )
                state.update(partial)  # type: ignore[arg-type]
                if node == "critic":
                    self._persist_evaluation(state)
                executed += 1
                node = self._next_node(node, state)
                state["resume_at"] = node
                self._sync_counters(state)
                self.db.commit()

            if node in TERMINAL_NODES and self.run.status == RunStatus.RUNNING:
                state["done"] = True
                self.run.status = RunStatus.COMPLETED
                self.run.finished_at = _now()
                self.emit(
                    EventType.RUN_COMPLETED,
                    f"Run completed: {self.run.samples_approved} approved, "
                    f"{self.run.samples_rejected} rejected, {self.run.samples_review} to review",
                    {"cost_usd": self.run.total_cost_usd},
                )
            elif self.run.status == RunStatus.RUNNING and node not in TERMINAL_NODES:
                self.run.status = RunStatus.RUNNING
            self._sync_counters(state)
            self.db.commit()
            return state
        finally:
            unregister_runtime(str(self.run.id))

    def _fail(self, state: EvaluationState, node: str, exc: AuraError) -> EvaluationState:
        meta = dict(state.get("execution_metadata") or {})
        chain = meta.setdefault("failure_chain", [])
        chain.append({"agent": node, "error": exc.code})
        state["execution_metadata"] = meta
        self.run.status = RunStatus.FAILED
        self.run.finished_at = _now()
        self.run.error = {
            "error": "WORKFLOW_EXECUTION_FAILED",
            "message": f"{node} agent failed: {exc.message}",
            "node": node,
            "code": exc.code,
            "retryable": bool(exc.retryable),
        }
        self.emit(
            EventType.RUN_FAILED,
            f"Run failed at '{node}': {exc.code}",
            {"node": node, "code": exc.code},
        )
        self._sync_counters(state)
        self.db.commit()
        log.error("workflow.failed node=%s code=%s", node, exc.code)
        return state

    async def run_to_completion(self, slice_steps: int | None = None) -> EvaluationState:
        """Drive slices until the run reaches a terminal status."""
        state: EvaluationState = dict(self.run.state or {})  # type: ignore[assignment]
        guard = 0
        max_slices = 500
        while guard < max_slices:
            guard += 1
            state = await self.advance(slice_steps)
            if self.run.status in (
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.STOPPED,
            ):
                break
        return state


def initialise_state(
    run: WorkflowRun, *, task: str, sop: dict[str, Any], config: dict[str, Any]
) -> EvaluationState:
    return new_state(run_id=str(run.id), task=task, sop=sop, config=config)
