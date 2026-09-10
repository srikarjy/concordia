"""Deterministic mutation over explicitly permitted digital-genome fields."""

from __future__ import annotations

import random
from typing import Any

from pydantic import ValidationError

from concordia.genomes.schema import (
    AgentGenome,
    EvidenceFamily,
    MutationOperator,
    MutationRecord,
    WorkflowStep,
    create_genome,
    genome_digest,
)

WINDOW_SIZES = (8, 12, 16, 24)
EVIDENCE_THRESHOLDS = (0.5, 0.65, 0.75, 0.85)
UNCERTAINTY_PROMPTS = ("uncertainty-v1", "uncertainty-v2")
COMPATIBLE_TOOLS = {
    "graph.query": "lineage.backtrack",
    "lineage.backtrack": "graph.query",
}


class MutationEngine:
    def mutate(
        self, parent: AgentGenome, operator: MutationOperator, seed: int
    ) -> tuple[AgentGenome | None, MutationRecord]:
        rng = random.Random(seed)
        content = parent.model_dump(mode="json", exclude={"genome_id"})
        content["parent_genome_id"] = parent.genome_id
        old_value: Any = None
        new_value: Any = None
        try:
            old_value, new_value = self._apply(content, operator, rng)
            child = create_genome(**content)
            mutation_id = genome_digest(
                {
                    "parent": parent.genome_id,
                    "child": child.genome_id,
                    "operator": operator,
                    "seed": seed,
                    "old": old_value,
                    "new": new_value,
                }
            )
            return child, MutationRecord(
                mutation_id=mutation_id,
                parent_genome_id=parent.genome_id,
                child_genome_id=child.genome_id,
                operator=operator,
                seed=seed,
                old_value=old_value,
                new_value=new_value,
                validation_result="VALID",
            )
        except (ValueError, ValidationError) as error:
            child_id = genome_digest(
                {"parent": parent.genome_id, "operator": operator, "seed": seed}
            )
            mutation_id = genome_digest(
                {"invalid_child": child_id, "operator": operator, "seed": seed}
            )
            return None, MutationRecord(
                mutation_id=mutation_id,
                parent_genome_id=parent.genome_id,
                child_genome_id=child_id,
                operator=operator,
                seed=seed,
                old_value=old_value,
                new_value=new_value,
                validation_result="INVALID",
                validation_error=str(error),
            )

    def _apply(
        self, content: dict[str, Any], operator: MutationOperator, rng: random.Random
    ) -> tuple[Any, Any]:
        workflow = [WorkflowStep.model_validate(value) for value in content["workflow"]]
        if operator is MutationOperator.ADD_VERIFICATION_STEP:
            if any(step.step_id == "lineage-backtrack" for step in workflow):
                raise ValueError("verification step is already present")
            step = WorkflowStep(
                step_id="lineage-backtrack",
                tool_name="lineage.backtrack",
                tool_version="1.0.0",
                evidence_family=EvidenceFamily.ATTRIBUTION,
                required=False,
                depends_on=("counterfactual-scan",),
            )
            content["workflow"] = [*workflow, step]
            return None, step.model_dump(mode="json")
        if operator is MutationOperator.REMOVE_OPTIONAL_VERIFICATION_STEP:
            optional = [step for step in workflow if not step.required]
            if not optional:
                raise ValueError("workflow has no optional verification step")
            selected = optional[rng.randrange(len(optional))]
            content["workflow"] = [step for step in workflow if step.step_id != selected.step_id]
            return selected.model_dump(mode="json"), None
        if operator is MutationOperator.REPLACE_COMPATIBLE_STEP:
            compatible = [step for step in workflow if step.tool_name in COMPATIBLE_TOOLS]
            if not compatible:
                raise ValueError("workflow has no compatible replacement")
            selected = compatible[rng.randrange(len(compatible))]
            replacement = selected.model_copy(
                update={"tool_name": COMPATIBLE_TOOLS[selected.tool_name]}
            )
            content["workflow"] = [
                replacement if step.step_id == selected.step_id else step for step in workflow
            ]
            return selected.model_dump(mode="json"), replacement.model_dump(mode="json")
        if operator is MutationOperator.REORDER_INDEPENDENT_STEPS:
            pairs = []
            for left in range(len(workflow)):
                for right in range(left + 1, len(workflow)):
                    candidate = list(workflow)
                    candidate[left], candidate[right] = candidate[right], candidate[left]
                    seen: set[str] = set()
                    valid = True
                    for step in candidate:
                        if any(dependency not in seen for dependency in step.depends_on):
                            valid = False
                            break
                        seen.add(step.step_id)
                    if valid:
                        pairs.append((left, right))
            if not pairs:
                raise ValueError("workflow has no independent steps to reorder")
            left, right = pairs[rng.randrange(len(pairs))]
            old_order = [step.step_id for step in workflow]
            workflow[left], workflow[right] = workflow[right], workflow[left]
            content["workflow"] = workflow
            return old_order, [step.step_id for step in workflow]
        if operator is MutationOperator.CHANGE_WINDOW_SIZE:
            old_window = int(content["attribution"]["window_size"])
            window_choices = [value for value in WINDOW_SIZES if value != old_window]
            new_window = window_choices[rng.randrange(len(window_choices))]
            content["attribution"]["window_size"] = new_window
            return old_window, new_window
        if operator is MutationOperator.CHANGE_EVIDENCE_THRESHOLD:
            old_threshold = float(content["verification"]["evidence_threshold"])
            threshold_choices = [
                value for value in EVIDENCE_THRESHOLDS if value != old_threshold
            ]
            new_threshold = threshold_choices[rng.randrange(len(threshold_choices))]
            content["verification"]["evidence_threshold"] = new_threshold
            return old_threshold, new_threshold
        if operator is MutationOperator.CHANGE_RESOURCE_BUDGET:
            old_resources = dict(content["resources"])
            budget_choices = [2, 4, 6, 8]
            budget_choices.remove(int(old_resources["max_tool_calls"]))
            content["resources"]["max_tool_calls"] = budget_choices[
                rng.randrange(len(budget_choices))
            ]
            return old_resources, dict(content["resources"])
        if operator is MutationOperator.SELECT_UNCERTAINTY_PROMPT:
            old_prompt = content["uncertainty_prompt_version"]
            prompt_choices = [
                value for value in UNCERTAINTY_PROMPTS if value != old_prompt
            ]
            new_prompt = prompt_choices[rng.randrange(len(prompt_choices))]
            content["uncertainty_prompt_version"] = new_prompt
            return old_prompt, new_prompt
        raise ValueError(f"unsupported mutation operator: {operator}")
