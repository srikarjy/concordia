# Local seed scientist

The genomic seed runtime accepts a frozen task and runs one local model through a bounded conversation. Each invocation starts with fresh messages. The older molecular packet interpreter remains a separate interface.

The four allowed turns are `ToolRequest`, `GraphQueryRequest`, `VerificationRequest`, and `FinalScientificResponse`. They form a discriminated schema: a final response cannot also request a tool, edit policy, or assign claim verification status. Proposed claims must cite identifiers declared in the frozen evidence graph and include scope, uncertainty, and confidence. Reference checks establish identifier validity; they do not establish that claim text is scientifically correct.

Requests for graph paths and verification use the frozen task's graph. Approved calls go through the Phase 4 executor, which records tool events and provenance artifacts. An undeclared tool, failed tool, invalid response, or exhausted turn budget ends the session and preserves the failure. There is no automatic schema-repair conversation or retry for an unfavorable answer.

## Persistence

Before inference, the runtime stores the task, versioned prompt, turn schema, exact conversation, model settings, policy, and budgets in content-addressed storage. Returned text is preserved before schema validation. The execution record links each request, raw response, model metadata, and tool result. Completed qualification records are discoverable through the durable event ledger and can be reused without calling the model again. Interrupted inference requires inspection; the command does not automatically repeat it.

The Ollama adapter restricts its endpoint to loopback, requires `OLLAMA_NO_CLOUD=1`, and records the local checkpoint digest and quantization metadata. It disables model reasoning traces, requests JSON output, and validates the complete turn schema locally. This accommodates local runtimes whose decoding grammar does not support the union schema. Each call requests at most 1,024 generated tokens, uses an 8,192-token context, has a 300-second transport timeout, and uses a one-second model keep-alive so the scientific tool process can reclaim memory between turns. The session permits four turns.

## Qualification

Use installed models and a dedicated state directory:

```bash
OLLAMA_NO_CLOUD=1 concordia qualify-scientist \
  --model phi3:latest --model gemma3:270m \
  --repetitions 2 --state-root .concordia/qualification
```

The command freezes criteria and a software fixture task before inference, executes candidates sequentially, and writes an immutable report plus `qualification.json`, a replaceable convenience pointer. Raw artifacts and the event database remain in the selected directory. Do not run the general genomic worker against this dedicated qualification directory.

The declared acceptance thresholds are:

| Component | Threshold and interpretation |
| --- | --- |
| JSON validity | 100% of model turns parse as JSON |
| Tool-request validity | At least 50% of repetitions include a successful approved tool call |
| Claim-schema validity | 100% of repetitions produce a schema-valid final response |
| Evidence-reference correctness | 100% produce nonempty claims citing only declared nodes |
| Repeated-run stability | At least 50% share an identical serialized final response |

Failed final responses contribute zero to stability. The score weights these components by 0.25, 0.20, 0.25, 0.20, and 0.10 respectively. Only candidates passing every threshold can be selected. Ties use lower mean per-call latency, lower measured memory, then model name. Memory is the runtime's reported resident model size, not a sampled peak of total process memory; absent measurements remain null. Token counts and latency are stored separately.

This small fixture qualification measures software protocol behavior. It does not qualify biological judgment, establish scientific support, or demonstrate general performance on genomic research tasks. The two-repetition default gives only a coarse stability measure. A stronger qualification cohort and real genomic evidence remain future work.

## Recorded development qualification

The first run requested the complete union schema as an Ollama decoding grammar. Both installed candidates failed at grammar initialization in both repetitions. Those four failed executions remain in `.concordia/qualification-phase5/`.

The transport was corrected to request JSON, with the same full schema validated by Concordia. A new protocol and state directory, `.concordia/qualification-phase5-json-v1/`, preserve the second run separately:

| Candidate | Checkpoint SHA-256 | Two-repetition outcome |
| --- | --- | --- |
| `phi3:latest` | `633fc5be925f9a484b61d6f9b9a78021eeb462100bd557309f01ba84cac26adf` | Two model-call timeouts; no response metrics available |
| `gemma3:270m` | `735af2139dc652bf01112746474883d79a52fa1c19038265d363e3d42556f7a2` | Two truncated JSON outputs at the 1,024-token limit |

Neither candidate passed any acceptance threshold. Resource contention occurred during this development run, including failures in timing-sensitive software tests running concurrently. This run does not establish model performance on an otherwise idle machine. Saved execution artifacts permit deterministic recalculation without new model calls; raw artifacts remain local and are excluded from Git.

`qwen3:1.7b` was then evaluated locally. Version 2 clarified the exact lowercase final-turn discriminator and used a one-second Ollama keep-alive; both graph requests succeeded, one final response passed, and one omitted a required claim field. Version 3 made the six required claim fields explicit without changing the task or acceptance thresholds. Both version 3 repetitions passed every component and produced identical final responses.

| Selected model | Checkpoint SHA-256 | JSON | Tool | Claim schema | References | Stability | Mean call latency | Report SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `qwen3:1.7b` | `3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6` | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 32.85 s | `c681b6a4e70146feee373179ff78e7bf86a99e3d5c112087da80fb855bcea33c` |

The selected model used about 2.36 GB of runtime-reported resident model memory, averaged 2,045.5 input tokens and 345 output tokens per call, and received a qualification score of 1.0. The report digest identifies the content-addressed local qualification report; the underlying raw model artifacts remain excluded from Git. Phase 5 is complete for this software gate.
