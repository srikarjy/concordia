from __future__ import annotations

import json

import pytest

from concordia.events.sqlite import (
    ConcurrencyError,
    IdempotencyConflictError,
    SQLiteEventLedger,
)
from concordia.genomics.schema import GenomicSequence
from concordia.runtime.contracts import RunStatus
from concordia.runtime.service import CreateRunRequest, RunService
from concordia.runtime.state_machine import IllegalTransitionError, validate_transition


def fixture_request(key: str = "fixture-run-1") -> CreateRunRequest:
    return CreateRunRequest(
        idempotency_key=key,
        sequence=GenomicSequence(
            sequence_id="fixture:sequence-1",
            sequence="ACGTTGCAACGT",
            assembly="GRCh38",
            region="chr1:0-12",
            strand="+",
        ),
        scan_position=4,
    )


def test_illegal_transition_is_rejected_without_an_event(tmp_path) -> None:
    service = RunService.local(tmp_path)
    record = service.create_and_execute(fixture_request())
    before = service.ledger.all_events(record.spec.run_id)

    with pytest.raises(IllegalTransitionError, match="illegal run transition"):
        service.transition(record.spec.run_id, RunStatus.EXECUTING)

    assert service.ledger.all_events(record.spec.run_id) == before
    with pytest.raises(IllegalTransitionError):
        validate_transition(RunStatus.COMPLETED, RunStatus.CANCELLED)


def test_create_is_idempotent_and_conflicting_payload_is_rejected(tmp_path) -> None:
    service = RunService.local(tmp_path)
    first = service.create_and_execute(fixture_request())
    event_count = len(service.ledger.all_events(first.spec.run_id))

    duplicate = service.create_and_execute(fixture_request())

    assert duplicate.spec.run_id == first.spec.run_id
    assert len(service.ledger.all_events(first.spec.run_id)) == event_count
    changed = fixture_request().model_copy(update={"scan_position": 5})
    with pytest.raises(IdempotencyConflictError):
        service.create_and_execute(changed)


def test_replay_and_restart_reconstruct_completed_fixture_run(tmp_path) -> None:
    first_service = RunService.local(tmp_path)
    created = first_service.create_and_execute(fixture_request())
    assert created.current_status is RunStatus.COMPLETED

    restarted_service = RunService.local(tmp_path)
    recovered = restarted_service.get_run(created.spec.run_id)
    replayed = restarted_service.replay(created.spec.run_id)

    assert recovered == created
    assert replayed.run == created
    assert replayed.event_count == created.last_sequence_number
    references = restarted_service.artifact_references(created.spec.run_id)
    assert len(references) == 5
    assert all(not reference.scientific_use_allowed for reference in references)
    event_ids = {
        event.event_id for event in restarted_service.ledger.all_events(created.spec.run_id)
    }
    for reference in references:
        assert reference.producing_event in event_ids
        assert len(restarted_service.artifacts.get_bytes(reference.digest)) == reference.byte_size

    backtrack_events = [
        event
        for event in restarted_service.ledger.all_events(created.spec.run_id)
        if event.event_type == "CLAIM_BACKTRACKED"
    ]
    assert backtrack_events[0].payload["verification_status"] == "UNVERIFIABLE"
    verification_reference = backtrack_events[0].payload["artifacts"][0]
    verification = json.loads(
        restarted_service.artifacts.get_bytes(verification_reference["digest"])
    )
    assert verification["scientific_use_allowed"] is False


def test_optimistic_append_and_pagination(tmp_path) -> None:
    service = RunService.local(tmp_path)
    record = service.create_and_execute(fixture_request())

    with pytest.raises(ConcurrencyError, match="expected run sequence"):
        service.ledger.append(
            record.spec.run_id,
            "STALE_WRITE",
            {},
            expected_sequence=record.last_sequence_number - 1,
        )

    first_page = service.ledger.events(record.spec.run_id, limit=3)
    assert [event.sequence_number for event in first_page.items] == [1, 2, 3]
    assert first_page.next_cursor == 3
    second_page = service.ledger.events(
        record.spec.run_id, after=first_page.next_cursor or 0, limit=500
    )
    assert second_page.items[0].sequence_number == 4
    assert second_page.next_cursor is None


def test_validation_failure_is_preserved_as_terminal_history(tmp_path) -> None:
    service = RunService.local(tmp_path)
    invalid = fixture_request("invalid-position").model_copy(update={"scan_position": 99})

    record = service.create_and_execute(invalid)

    assert record.current_status is RunStatus.FAILED_VALIDATION
    assert record.terminal_reason == "scan position exceeds sequence length"
    assert record.last_sequence_number == 8


def test_sqlite_uses_wal_and_schema_migration(tmp_path) -> None:
    ledger = SQLiteEventLedger(tmp_path / "ledger.sqlite3")
    with ledger._connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        migrations = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert journal_mode == "wal"
    assert [row[0] for row in migrations] == [1]
