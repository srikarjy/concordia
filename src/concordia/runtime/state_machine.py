"""Deterministic state transitions and event replay."""

from __future__ import annotations

from collections.abc import Iterable

from concordia.runtime.contracts import RunEvent, RunRecord, RunSpec, RunStatus

HAPPY_PATH = (
    RunStatus.CREATED,
    RunStatus.VALIDATING,
    RunStatus.INGESTING,
    RunStatus.GRAPH_READY,
    RunStatus.PLANNING,
    RunStatus.SCHEDULED,
    RunStatus.EXECUTING,
    RunStatus.CLAIM_VALIDATION,
    RunStatus.BACKTRACKING,
    RunStatus.EVALUATING,
    RunStatus.REPORTING,
    RunStatus.COMPLETED,
)

FAILURE_STATES = frozenset(
    {
        RunStatus.FAILED_VALIDATION,
        RunStatus.FAILED_POLICY,
        RunStatus.FAILED_TOOL,
        RunStatus.FAILED_MODEL,
        RunStatus.FAILED_SCHEMA,
        RunStatus.FAILED_ARTIFACT,
        RunStatus.TIMED_OUT,
        RunStatus.CANCELLED,
    }
)
TERMINAL_STATES = FAILURE_STATES | {RunStatus.COMPLETED}

TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    current: frozenset({following, *FAILURE_STATES})
    for current, following in zip(HAPPY_PATH, HAPPY_PATH[1:], strict=False)
}
TRANSITIONS[RunStatus.COMPLETED] = frozenset()
for terminal in FAILURE_STATES:
    TRANSITIONS[terminal] = frozenset()


class IllegalTransitionError(ValueError):
    """Raised before persistence when a state change is not permitted."""


def validate_transition(current: RunStatus, requested: RunStatus) -> None:
    if requested not in TRANSITIONS[current]:
        raise IllegalTransitionError(f"illegal run transition: {current} -> {requested}")


def reconstruct_run(events: Iterable[RunEvent]) -> RunRecord:
    ordered = tuple(events)
    if not ordered or ordered[0].event_type != "RUN_CREATED":
        raise ValueError("run event history must begin with RUN_CREATED")
    first = ordered[0]
    spec = RunSpec.model_validate(first.payload["spec"])
    current = RunStatus.CREATED
    previous_sequence = 0
    terminal_reason: str | None = None
    for event in ordered:
        if event.run_id != spec.run_id:
            raise ValueError("event history contains multiple run IDs")
        if event.sequence_number != previous_sequence + 1:
            raise ValueError("event history sequence is not contiguous")
        previous_sequence = event.sequence_number
        if event.event_type == "STATE_TRANSITIONED":
            recorded_from = RunStatus(event.payload["from_status"])
            requested = RunStatus(event.payload["to_status"])
            if recorded_from != current:
                raise ValueError("transition event does not match reconstructed state")
            validate_transition(current, requested)
            current = requested
            terminal_reason = event.payload.get("reason")
    return RunRecord(
        spec=spec,
        current_status=current,
        created_at=first.created_at,
        last_sequence_number=previous_sequence,
        terminal_reason=terminal_reason if current in TERMINAL_STATES else None,
    )
