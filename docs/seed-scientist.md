# Local seed scientist

The genomic seed runtime accepts a frozen task and runs one local model through a bounded conversation. Each invocation starts with fresh messages. The older molecular packet interpreter remains a separate interface.

The four allowed turns are `ToolRequest`, `GraphQueryRequest`, `VerificationRequest`, and `FinalScientificResponse`. They form a discriminated schema: a final response cannot also request a tool, edit policy, or assign claim verification status. Proposed claims must cite identifiers declared in the frozen evidence graph and include scope, uncertainty, and confidence. Reference checks establish identifier validity; they do not establish that claim text is scientifically correct.

Requests for graph paths and verification use the frozen task's graph. Approved calls go through the Phase 4 executor, which records tool events and provenance artifacts. An undeclared tool, failed tool, invalid response, or exhausted turn budget ends the session and preserves the failure. There is no automatic schema-repair conversation or retry for an unfavorable answer.

## Persistence

Before inference, the runtime stores the task, versioned prompt, turn schema, exact conversation, model settings, policy, and budgets in content-addressed storage. Returned text is preserved before schema validation. The execution record links each request, raw response, model metadata, and tool result. Completed qualification records are discoverable through the durable event ledger and can be reused without calling the model again. Interrupted inference requires inspection; the command does not automatically repeat it.

The Ollama adapter restricts its endpoint to loopback, requires `OLLAMA_NO_CLOUD=1`, and records the local checkpoint digest and quantization metadata. It requests JSON output and validates the complete turn schema locally. This accommodates local runtimes whose decoding grammar does not support the union schema. Each call requests at most 1,024 generated tokens, uses an 8,192-token context, and has a 300-second transport timeout. The session permits four turns.

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

Neither candidate passed any acceptance threshold. Selection is empty and Phase 5 is incomplete. Resource contention occurred during this development run, including failures in timing-sensitive software tests running concurrently. This run does not establish model performance on an otherwise idle machine. Qualification thresholds were not changed after these outcomes. Saved execution artifacts permit deterministic recalculation without new model calls; raw artifacts remain local and are excluded from Git.
