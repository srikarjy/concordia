from __future__ import annotations

import json

import httpx
import pytest

from concordia.scientist.adapters import OpenRouterScientistAdapter
from concordia.scientist.local_qualification import run_openrouter_qualification


def test_openrouter_adapter_accepts_only_free_models_and_requires_key() -> None:
    with pytest.raises(ValueError, match="free model"):
        OpenRouterScientistAdapter("qwen/qwen3")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterScientistAdapter(api_key="").generate([], {})


def test_openrouter_adapter_preserves_resolved_identity_without_secret() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "id": "generation-1",
                "model": "qwen/qwen3-4b:free",
                "choices": [{"message": {"content": '{"kind":"final_scientific_response"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    adapter = OpenRouterScientistAdapter(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    result = adapter.generate([{"role": "user", "content": "test"}], {"type": "object"})
    adapter.generate(
        [
            {"role": "assistant", "content": "query"},
            {"role": "tool", "content": '{"status":"success"}'},
        ],
        {"type": "object"},
    )

    assert result.model_identity == "qwen/qwen3-4b:free"
    assert result.input_tokens == 12
    assert "test-secret" not in json.dumps(result.model_dump(mode="json"))
    assert requests[0]["model"] == "openrouter/free"
    assert requests[1]["model"] == "qwen/qwen3-4b:free"
    assert requests[1]["messages"][1]["role"] == "user"  # type: ignore[index]
    assert "Deterministic tool result" in requests[1]["messages"][1]["content"]  # type: ignore[index]


def test_openrouter_adapter_preserves_safe_error_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "invalid message role"}})

    adapter = OpenRouterScientistAdapter(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match="invalid message role"):
        adapter.generate([{"role": "user", "content": "test"}], {})


def test_free_router_cannot_be_treated_as_one_repeated_checkpoint(tmp_path) -> None:
    with pytest.raises(ValueError, match="different models"):
        run_openrouter_qualification(tmp_path, repetitions=2)
