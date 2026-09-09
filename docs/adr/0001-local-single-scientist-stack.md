# ADR-0001: Local single-scientist runtime

**Status:** Accepted  
**Date:** 2026-09-08  
**Deciders:** Concordia project owner

## Context

Concordia needs one scientist language model to process frozen evidence packets independently across control and intervention conditions. The portfolio release must be usable by other researchers without a Concordia-hosted server, cloud database, queue, authentication system, or persistent external infrastructure. The evaluator must remain deterministic and must not generate a competing scientific answer.

The current development machine is an Apple Silicon laptop with 8 GB unified memory. The MVP also needs structured output, exact request/response capture, offline replay, and a stable model identity.

## Decision

Use plain Python orchestration and a local Ollama backend for development and pilot runs. Pass a Pydantic-generated JSON Schema to the local runtime, validate the returned JSON with Pydantic, and save the exact raw response before deriving metrics. Disable cloud features and bind inference to the local machine. Every condition receives an independent call with no shared conversation history.

Use a small quantized instruct model that fits the available machine. Qualify candidate models on development packets before freezing one model for the 30-molecule study. Record the model tag, digest, runtime version, quantization, prompt version, generation parameters, and hardware in the experiment manifest.

For a final locked run, permit a direct `llama.cpp` GGUF backend when it improves portability or makes the model file checksum easier to pin. This is a backend substitution behind the same scientist interface, not a second agent.

Store raw requests/responses as local JSON, claims and comparison rows as JSONL or Parquet, and manifests as canonical JSON. Use static HTML reports. Do not require a vector database, agent framework, hosted API, tracking server, or web application.

## Options considered

### Option A: Ollama locally

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | No service cost after model download |
| Portability | macOS, Linux, and Windows local workflows |
| Structured output | JSON Schema support |
| Reproducibility | Good when model digests and runtime versions are recorded |

**Pros:** simple installation, local API, quantized model catalog, practical on a laptop, and explicit local-only mode.  
**Cons:** a background localhost process is required; a mutable model tag must not be treated as an immutable identity.

### Option B: llama.cpp / llama-cpp-python

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | No service cost after model download |
| Portability | Strong with a pinned GGUF, subject to build details |
| Structured output | Grammar or JSON Schema constraints |
| Reproducibility | Very good with an exact GGUF checksum and pinned binary |

**Pros:** direct local inference, Metal support, and a clear model-file artifact.  
**Cons:** more model-template and build responsibility; less convenient for first-time users.

### Option C: vLLM locally

| Dimension | Assessment |
|---|---|
| Complexity | High on this laptop |
| Cost | No service cost, but requires suitable GPU hardware |
| Portability | Best on a Linux/NVIDIA workstation |
| Structured output | Strong offline support |
| Reproducibility | Good with pinned weights and environment |

**Pros:** efficient batched inference and structured outputs.  
**Cons:** unnecessary infrastructure for 270 calls on the current machine and a poor fit for Apple Silicon laptop distribution.

### Option D: LangChain, CrewAI, or AutoGen

These frameworks are intentionally not selected. Their agent and workflow abstractions solve tool use, state, memory, collaboration, or repeated orchestration. Concordia needs one controlled model invocation per packet, so their extra state and control paths would increase experimental confounding without adding a necessary capability.

## Consequences

- Other users can run the demo and full study locally with documented hardware profiles.
- Prompts and responses do not leave the machine during a local run.
- Model weights remain a separately downloaded artifact with their own license and checksum.
- Small local models may produce weaker scientific claims than hosted frontier models; that limitation becomes part of the study and must be reported.
- Model comparisons require separate experiment identifiers; their results cannot be silently pooled.
- A transport failure may be retried and logged. A schema failure remains a measured failure rather than triggering an unlogged self-correction call.

## Action items

1. [ ] Implement the provider-neutral scientist interface.
2. [ ] Add a local-only preflight that verifies Ollama, model digest, and cloud-disabled status.
3. [ ] Qualify candidate small models on development packets before selecting the MVP model.
4. [ ] Add a `demo` command with committed, clearly labeled fixture responses that requires no model download.
5. [ ] Add an optional direct llama.cpp backend after the local Ollama pilot is stable.
