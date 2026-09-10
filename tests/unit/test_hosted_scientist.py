from __future__ import annotations

import json

import httpx
import pytest

from concordia.scientist.adapters import OpenRouterScientistAdapter


def test_openrouter_adapter_accepts_only_free_models_and_requires_key() -> None:
    with pytest.raises(ValueError, match="free model"):
        OpenRouterScientistAdapter("qwen/qwen3")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterScientistAdapter(api_key="").generate([], {})


def test_openrouter_adapter_preserves_resolved_identity_without_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
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

    assert result.model_identity == "qwen/qwen3-4b:free"
    assert result.input_tokens == 12
    assert "test-secret" not in json.dumps(result.model_dump(mode="json"))
