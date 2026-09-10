# Local Scientific Tool Execution

Concordia can run its approved scientific tools without an installed CellForge service. The implementation provides a CellForge-compatible application boundary and a zero-cost local adapter. An external runtime can be added later without changing the scientific contracts, event records, or artifact format.

## Contracts

Every execution uses versioned, frozen Pydantic contracts:

- `ExecutionRequest` identifies the run, request, exact tool version, arguments, policy, and budget.
- `ExecutionResult` records status, validated output, bounded logs, structured errors, elapsed time, and scientific-use eligibility.
- `SandboxPolicy` allowlists tools and capabilities and declares network, filesystem, and readable-root policy.
- `ResourceBudget` bounds wall time, memory, and serialized output size.
- `ToolDefinition` declares input and output schemas, capabilities, network and filesystem requirements, path fields, and maximum resources.

Run `concordia list-tools` to inspect the exact JSON schemas and policies for the installed registry.

## Initial registry

| Tool | Responsibility | Capability |
| --- | --- | --- |
| `sequence.validate@1.0.0` | Validate a genomic sequence and coordinate metadata | `genomic.compute` |
| `variant.normalize@1.0.0` | Validate a reference allele and apply a variant | `genomic.compute` |
| `artifact.verify@1.0.0` | Recompute and verify an immutable artifact digest | `artifact.read` |
| `graph.query@1.0.0` | Find a declared path in a stored evidence graph | `artifact.read`, `graph.read` |
| `lineage.backtrack@1.0.0` | Backtrack a claim through a stored graph | `artifact.read`, `graph.read` |
| `evidence.verify@1.0.0` | Apply deterministic claim-path verification | `artifact.read`, `graph.read` |
| `xai.mutational_scan@1.0.0` | Run deterministic position-level fixture mutagenesis | `genomic.compute` |

These tools use no network or general filesystem access. Artifact reads are resolved through the content-addressed store, not caller-selected paths.

## Execution and provenance

The local adapter validates the tool allowlist, exact version, required capabilities, network and filesystem policy, resource ceilings, argument schema, and any declared paths before starting work. It then spawns a child process, changes into a fresh temporary directory, applies supported resource limits, disables Python socket creation, and invokes only the registered handler. Output is schema-validated and size-checked before it crosses the process boundary.

`ToolExecutionService` requires an executing durable run. It appends a start event containing the exact request, executes the adapter, stores the result and provenance graph by SHA-256, and appends a finish event containing both artifact references. Rejections and failures follow the same preservation path.

## Security boundary and limits

The design is deny-by-default and excludes arbitrary shell, arbitrary Python, undeclared tools, and network-enabled local policies. Repository paths, when a future tool needs them, must be relative to explicit readable roots and resolve to regular files without parent traversal or symlink escape. A separately bounded process-startup deadline ends when the child signals readiness; the declared tool timeout then bounds handler execution. Timeout termination and output limits preserve bounded partial logs for diagnosis.

The local adapter is process isolation for trusted Concordia handlers, not a container, virtual machine, or kernel-enforced hostile-code sandbox. On Linux it applies an address-space limit; on supported Unix systems it applies a CPU limit. Filesystem allowlists are validated by the parent but are not an OS-level jail. Use a future external CellForge adapter when the threat model includes untrusted executable code.

No current tool output is evidence of biological truth. Fixture scoring and fixture mutational scans always set `scientific_use_allowed=false`, and deterministic validation only establishes software or provenance properties.
