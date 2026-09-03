"""Dataset Builder Agent (§6): approved samples → dataset rows → serialised files."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from collections.abc import Iterable
from typing import Any

from app.agents.base import Agent
from app.models.enums import DatasetFormat, DatasetStyle


# --- row transformation -------------------------------------------------
def to_instruction(sample: dict[str, Any], evaluation: dict[str, Any] | None = None) -> dict:
    return {
        "instruction": sample.get("input", ""),
        "input": sample.get("extra", {}).get("context", "")
        if isinstance(sample.get("extra"), dict)
        else "",
        "output": sample.get("response", ""),
        "category": sample.get("category", "general"),
        "difficulty": sample.get("difficulty", "medium"),
    }


def to_chat(sample: dict[str, Any], evaluation: dict[str, Any] | None = None) -> dict:
    return {
        "messages": [
            {"role": "user", "content": sample.get("input", "")},
            {"role": "assistant", "content": sample.get("response", "")},
        ],
        "metadata": {
            "category": sample.get("category", "general"),
            "difficulty": sample.get("difficulty", "medium"),
        },
    }


def to_evaluation(sample: dict[str, Any], evaluation: dict[str, Any] | None = None) -> dict:
    return {
        "prompt": sample.get("input", ""),
        "response": sample.get("response", ""),
        "reference": sample.get("reference") or "",
        "score": round(float((evaluation or {}).get("overall_score", 0)), 2),
        "category": sample.get("category", "general"),
    }


TRANSFORMS = {
    DatasetStyle.INSTRUCTION: to_instruction,
    DatasetStyle.CHAT: to_chat,
    DatasetStyle.EVALUATION: to_evaluation,
}


def build_rows(
    items: Iterable[tuple[dict[str, Any], dict[str, Any] | None]], style: str
) -> list[dict[str, Any]]:
    fn = TRANSFORMS[DatasetStyle(style)]
    return [fn(sample, evaluation) for sample, evaluation in items]


# --- serialisation ------------------------------------------------------
def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        out[k] = (
            v
            if isinstance(v, (str, int, float, bool)) or v is None
            else json.dumps(v, ensure_ascii=False)
        )
    return out


def serialize(rows: list[dict[str, Any]], fmt: str) -> tuple[bytes, str]:
    """Return (payload, media_type). Parquet degrades to JSONL if pyarrow absent."""
    f = DatasetFormat(fmt)
    if f is DatasetFormat.JSON:
        return json.dumps(rows, indent=2, ensure_ascii=False).encode(), "application/json"
    if f is DatasetFormat.JSONL:
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        return body.encode(), "application/x-ndjson"
    if f is DatasetFormat.CSV:
        flat = [_flatten(r) for r in rows]
        fields: list[str] = []
        for r in flat:
            for k in r:
                if k not in fields:
                    fields.append(k)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat)
        return buf.getvalue().encode(), "text/csv"
    # Parquet (§6 "if practical")
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore

        table = pa.Table.from_pylist([_flatten(r) for r in rows])
        sink = io.BytesIO()
        pq.write_table(table, sink)
        return sink.getvalue(), "application/vnd.apache.parquet"
    except ModuleNotFoundError:
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        return body.encode(), "application/x-ndjson"


def checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class DatasetBuilderAgent(Agent):
    name = "dataset_builder"
    prompt_key = "dataset_builder"

    def run(
        self,
        *,
        items: list[tuple[dict[str, Any], dict[str, Any] | None]],
        style: str,
        formats: list[str],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        rows = build_rows(items, style)
        artifacts = []
        for fmt in formats:
            payload, media = serialize(rows, fmt)
            artifacts.append(
                {
                    "format": fmt,
                    "media_type": media,
                    "size_bytes": len(payload),
                    "checksum": checksum(payload),
                }
            )
        out = {
            "style": style,
            "row_count": len(rows),
            "formats": formats,
            "artifacts": artifacts,
            "rows": rows,
        }
        self.local_telemetry(
            status="SUCCESS",
            input_json={"item_count": len(items), "style": style, "formats": formats},
            output_json={k: v for k, v in out.items() if k != "rows"},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return out
