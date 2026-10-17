# Concordia for Boston biotech teams

*An audit layer for AI-generated biology. It records which model made a claim, on which input, and
whether the claim survived independent checks, so your team and your partners can replay it.*

## The problem you already have

Your team runs structure and sequence models (Boltz-2, Evo 2, ESM and friends) and designs
candidates from them. Three questions keep coming back, from your own scientists, your board, a CRO,
or a pharma partner doing diligence:

1. **Which model, which checkpoint, which input produced this result?** Often the answer is a notebook.
2. **Does the claim survive a perturbation, or is it a pretty picture?** Attribution maps and
   confidence scores look convincing and prove nothing causal.
3. **Can someone else replay it and get the same answer?** Re-running is expensive, and silent model
   or parameter drift makes it unreliable.

Concordia answers those mechanically and keeps the receipt.

## How each feature helps you

| Feature | What it does | Why it matters to a founder |
|---|---|---|
| **Content-addressed artifacts** | Every input, output and request is stored by SHA-256; a 1-byte change is refused (`409`). | Tamper-evident records you can hand to a partner or auditor. |
| **Experiment DAG** | DNA, protein, structure and model-run nodes on immutable branches, with compare and a deterministic replay manifest. | A design campaign becomes a reviewable history, not a folder of files. |
| **Antibody validation tool** | Rejects malformed heavy/light/nanobody inputs, missing antigens and out-of-range epitopes before any compute is spent. | Catches expensive input mistakes before a GPU run. |
| **Boltz-2 complex prediction** | Antibody-antigen complex via NVIDIA's hosted NIM, with request and response artifacts recorded. | Structure hypotheses arrive with provenance attached. |
| **Claim verifier** | Rule-based, no LLM judge: needs independent evidence families, a passing counterfactual and in-scope inputs. | The tool says "unverifiable" when it should. That honesty is the product. |
| **Colony of workflow variants** | Bounded variants of an analysis workflow, selected by deterministic fitness; members that give no valid response cannot survive. | A principled way to compare analysis strategies without a model grading itself. |
| **Event ledger and replay** | Append-only events, resumable runs, streaming progress. | Interrupted runs resume; every step is auditable. |
| **Read-only tool API (OpenAPI)** | Six read-only operations any agent or client can import. | Plugs into your internal agents without exposing write access. |
| **Security posture** | Capability tokens per experiment, no client self-certification of scientific use, per-client and global limits, CSP and security headers, non-root container. | You can put it in front of collaborators. |

## Three-minute demo

1. **Open the workspace.** Four regional claims, each marked `UNVERIFIABLE` with the exact reasons
   (insufficient independent evidence, ineligible evidence, counterfactual absent).
2. **Trace a claim.** Claim, evidence, artifact, hash. Change one byte of the artifact and the API refuses it.
3. **Branch an experiment.** Reference sequence, an edit, and an alternative branch. Compare shows
   the differing positions. The replay manifest is identical on every read.
4. **Validate an antibody.** A valid heavy, light and antigen request passes. A missing light chain
   or an epitope outside the antigen is rejected with a specific message.
5. **Run a colony.** A fresh execution with full lineage of mutations and selections.

## What is real, and what is not (say this first)

- **Real and tested:** the audit layer, experiment DAG, claim verifier, replay, integrity checks,
  security controls, and the Boltz-2 integration code. The Python and browser test suites run in CI.
- **First real measurement:** the live Boltz-2 integration reproduced the HyHEL-10 Fab and lysozyme
  complex (PDB 3HFM) in about 5 seconds. Against the crystal structure: per-chain CA RMSD 0.76 to
  1.55 Å, antigen placement 2.07 Å in the antibody frame, and 81% of crystal interface contacts
  recovered at 74% precision. This is a known, old structure that is likely in the model's
  training data, so it shows the pipeline works, not that the model generalizes. See
  `reports/boltz2-3hfm-reference-reproduction.json`.
- **Not yet real:** there is **no novel or validated scientific finding** in this repository. Evo 2
  generation and a strict forward-worker boundary are integrated, but no real forward score has
  passed the frozen study protocol. RFdiffusion and ProteinMPNN are integrated as hosted campaign
  adapters; RFantibody is not integrated. All fixture output is labeled `scientific_use_allowed=false`.
- **Why that is a feature:** the system refuses to overclaim, which is exactly what a diligence
  reviewer wants from the layer that sits under model outputs.

## What I want from you

A design partner. Bring one real campaign, such as an antibody-antigen pair you already modeled, ideally one
released after the model's training cutoff. I will run it end to end, deliver the artifacts, the replay manifest and a verifier report that
states plainly where the evidence is and is not sufficient, and show you where the verifier
disagrees with the model. In return I want honest feedback on what your team would need before
trusting it with a real decision.

## Links

- Code: https://github.com/srikarjy/concordia
- Live workspace: https://srikarjy025-concordia-colony.hf.space (read-only demonstration)
- Technical guide, limits and security notes: `docs/guide.md`
