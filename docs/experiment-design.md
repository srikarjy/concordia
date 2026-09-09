# Experiment Design

## Primary question

Does a scientist LLM adjust its scientific claims and confidence appropriately when molecular-model explanation evidence is withheld or replaced while the prediction and other context remain fixed?

## Hypotheses

- Explanation-dependent claims should be removed, weakened, or explicitly qualified when explanation evidence is withheld.
- Shuffled explanation evidence may change attribution-based claims; confidently treating it as support for the recipient molecule is a failure mode.
- Claims grounded only in the unchanged prediction need not change across conditions.
- The study may find weak, null, heterogeneous, or undesirable effects. No direction is treated as established in advance.

## Experimental unit and variables

The primary experimental unit is a held-out molecule. Condition is the independent variable: control, explanation withheld, or explanation shuffled. A later extension may add deterministic corruption after the minimal protocol is validated.

Dependent variables include claim retention, additions, removals, matched-claim confidence shifts, evidence-reference changes, unsupported claims, contradictions, and intervention sensitivity. Repeated LLM generations estimate within-molecule variability; they do not increase the molecule sample size.

## Controls

The control packet contains the frozen predictor output and its matching explanation. Intervention packets retain molecule identity, prediction, documents, prompt version, response schema, model identifier, and generation settings. The scientist receives each packet in a fresh context and does not see condition names or other responses.

## Initial sample

The target is approximately 30 NR-AhR molecules selected from a held-out split. Selection criteria and class/confidence coverage must be frozen before inspecting LLM results. The model trains on a separate, larger partition. This is an exploratory study, so estimates require uncertainty intervals and cautious interpretation.

## Repeated runs

Repeat count, temperature, seed support, retry policy, and ordering are fixed in the experiment manifest. Conditions should be randomized or balanced in collection order to reduce time-dependent provider effects. Schema failures and exhausted retries remain visible in the analysis.

## Confounders

- Predictor errors can make a matching explanation faithfully explain an incorrect prediction.
- Fingerprint bits can collide or correspond to multiple atom environments.
- Missing-evidence language, packet length, or formatting can reveal the condition.
- Shuffled donor molecules may differ in class, size, fingerprint density, or prediction confidence.
- The LLM may use memorized chemical knowledge rather than supplied evidence.
- Hosted model behavior can drift despite a stable model name and parameters.
- Curated documents can support claims independently of the explanation intervention.

These factors will be measured, matched, held constant, or reported as limitations where possible.

## Data leakage prevention

Canonical duplicates remain in one split. Bemis–Murcko scaffold groups remain in one split. Hyperparameters and probability thresholds are selected without the test set. The approximately 30-molecule LLM cohort is frozen from held-out data without choosing examples for interesting LLM behavior. Documents and prompts are finalized before the main response collection.

## Evaluation strategy

Mechanical checks validate schemas and evidence-reference existence. Fixed matching rules compare structured claims. Scientific support and semantic contradiction, where rules are insufficient, use a predefined human rubric with independent review on a useful subset. The deterministic evaluator aggregates these inputs; no second LLM supplies a preferred answer.

Sensitivity is interpreted by claim type. A model that changes every claim is not automatically faithful, and a model that retains a prediction-grounded statement is not automatically insensitive.

## Why evidence is frozen

Live model inference, explanation generation, or document retrieval could change between conditions and runs. Frozen, content-hashed packets isolate the intended intervention and let saved LLM responses be reevaluated under revised metrics without rerunning upstream stages.
