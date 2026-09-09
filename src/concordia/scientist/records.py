"""Persist exact scientist requests and responses for replayable experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from concordia.evidence.schema import EvidencePacket
from concordia.scientist.ollama import ScientistGeneration
from concordia.scientist.prompt import PROMPT_VERSION, render_messages


class ScientistRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    packet_id: str = Field(min_length=1)
    packet_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    condition: str = Field(min_length=1)
    prompt_version: str = PROMPT_VERSION
    messages: list[dict[str, str]]
    model_requested: str = Field(min_length=1)
    generation: dict[str, Any]
    raw_response: str
    parsed_response: dict[str, Any] | None = None
    validation_error: str | None = None

    @classmethod
    def from_generation(
        cls,
        packet: EvidencePacket,
        condition: str,
        model: str,
        generation: ScientistGeneration,
    ) -> ScientistRunRecord:
        return cls(
            packet_id=packet.packet_id,
            packet_hash=packet.content_hash(),
            condition=condition,
            messages=render_messages(packet),
            model_requested=model,
            generation=generation.metadata,
            raw_response=generation.raw_response,
            parsed_response=(
                generation.parsed.model_dump(mode="json") if generation.parsed is not None else None
            ),
            validation_error=generation.validation_error,
        )

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def write_record(record: ScientistRunRecord, directory: str | Path) -> Path:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{record.content_hash()}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(record.canonical_json() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def read_record(path: str | Path) -> ScientistRunRecord:
    record = ScientistRunRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if record.content_hash() != Path(path).stem:
        raise ValueError(f"Scientist record hash mismatch for {path}")
    return record
