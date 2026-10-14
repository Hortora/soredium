"""Typed LLM interface for orchestrator judgment steps (#451).

Defines the contract between orchestrator engine and LLM:
- StepType enum replaces stringly-typed step classification
- Outcome enum for structured judgment responses
- JudgmentRequest/Response dataclasses for typed request/response
- Serialization and validation functions
"""

import json
from dataclasses import dataclass
from enum import Enum


class StepType(Enum):
    MECHANICAL = "mechanical"
    JUDGMENT = "judgment"
    LIFECYCLE = "lifecycle"


class Outcome(Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class JudgmentRequest:
    step: str
    handler: str | None
    context: dict
    response_schema: dict
    skippable: bool
    timeout_hint: str


@dataclass(frozen=True)
class JudgmentResponse:
    step: str
    outcome: Outcome
    produced: int
    evidence: dict
    block_reason: str | None


PRODUCED_REQUIRED_SCHEMA = {
    "type": "object",
    "properties": {
        "step": {"type": "string"},
        "outcome": {"type": "string", "enum": ["completed", "skipped", "blocked"]},
        "produced": {"type": "integer", "minimum": 0},
        "evidence": {"type": "object"},
        "block_reason": {"type": ["string", "null"]},
    },
    "required": ["step", "outcome", "produced"],
}

DEFAULT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "step": {"type": "string"},
        "outcome": {"type": "string", "enum": ["completed", "skipped", "blocked"]},
        "produced": {"type": "integer", "minimum": 0},
        "evidence": {"type": "object"},
        "block_reason": {"type": ["string", "null"]},
    },
    "required": ["step", "outcome", "produced"],
}


def serialize_request(request: JudgmentRequest) -> dict[str, str]:
    result: dict[str, str] = {"ACTION": request.step}
    if request.handler:
        result["HANDLER"] = request.handler
    result.update(request.context)
    result["SCHEMA"] = json.dumps(request.response_schema)
    result["SKIPPABLE"] = "yes" if request.skippable else "no"
    result["TIMEOUT_HINT"] = request.timeout_hint
    result["COMPLETE_WITH"] = (
        f"step_done={request.step} outcome=completed produced=N"
    )
    return result


def parse_response(args: dict[str, str]) -> JudgmentResponse:
    step = args.get("step_done", "")
    outcome_str = args.get("outcome", "completed")
    outcome = Outcome(outcome_str)
    produced_raw = args.get("produced", "0")
    try:
        produced = int(produced_raw)
    except (ValueError, TypeError):
        produced = 0
    evidence_raw = args.get("evidence", "{}")
    try:
        evidence = json.loads(evidence_raw) if evidence_raw else {}
    except (json.JSONDecodeError, TypeError):
        evidence = {}
    block_reason = args.get("block_reason")
    return JudgmentResponse(step, outcome, produced, evidence, block_reason)


def validate_response(response: JudgmentResponse, schema: dict) -> list[str]:
    errors: list[str] = []
    resp_dict = {
        "step": response.step,
        "outcome": response.outcome.value,
        "produced": response.produced,
        "evidence": response.evidence,
        "block_reason": response.block_reason,
    }
    required = schema.get("required", [])
    for field in required:
        if field not in resp_dict or resp_dict[field] is None:
            errors.append(f"missing required field: {field}")
    props = schema.get("properties", {})
    if "outcome" in props and "enum" in props["outcome"]:
        if resp_dict.get("outcome") not in props["outcome"]["enum"]:
            errors.append(f"invalid outcome: {resp_dict.get('outcome')}")
    if "produced" in props:
        p = resp_dict.get("produced")
        if not isinstance(p, int):
            errors.append(f"produced must be integer, got {type(p).__name__}")
        elif "minimum" in props["produced"] and p < props["produced"]["minimum"]:
            errors.append(f"produced must be >= {props['produced']['minimum']}")
    return errors
