"""Inference engine wrapping the ConceptCLIP checkpoint.

Model: https://hf.co/JerrryNie/ConceptCLIP (gated — requires accepting the
license on the model page and an authenticated `HF_TOKEN`).

ConceptCLIP is zero-shot: there's no fixed label set, only a list of
candidate concept strings supplied per call. `predict` scores the image
against those candidates; `region_heatmap` produces a best-effort
region-concept alignment map for a chosen concept via gradients on the
vision tower's patch tokens (a ViT Grad-CAM variant). The exact attention
API for this checkpoint hasn't been exercised against real gated access
yet, so `region_heatmap` degrades to `None` on any shape/attribute
mismatch rather than crashing the caller — see the `heatmap_error` field
on `Prediction`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import torch
from PIL import Image

MODEL_ID = "JerrryNie/ConceptCLIP"


@dataclass
class ConceptScore:
    concept: str
    score: float


@dataclass
class Prediction:
    scores: list[ConceptScore]
    top_concepts: list[str] = field(init=False)
    heatmaps: dict[str, np.ndarray | None] = field(default_factory=dict)
    heatmap_error: str | None = None

    def __post_init__(self) -> None:
        self.top_concepts = [s.concept for s in self.scores]


class ConceptClipEngine:
    """Loads ConceptCLIP once; reused across calls."""

    def __init__(self, model_id: str = MODEL_ID, device: str | None = None) -> None:
        from transformers import AutoModel, AutoProcessor

        token = os.environ.get("HF_TOKEN")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = AutoModel.from_pretrained(
            model_id, trust_remote_code=True, token=token
        ).to(self.device)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(
            model_id, trust_remote_code=True, token=token
        )

    @torch.no_grad()
    def predict(
        self, image: Image.Image, candidate_concepts: list[str], top_k: int = 3
    ) -> Prediction:
        """Zero-shot score `image` against `candidate_concepts`.

        Returns the top-`k` concepts by cosine similarity (softmax-normalized
        over the candidate set), highest first.
        """
        if not candidate_concepts:
            raise ValueError("candidate_concepts must be non-empty")

        inputs = self.processor(
            text=candidate_concepts,
            images=image,
            return_tensors="pt",
            padding=True,
        ).to(self.device)

        outputs = self.model(**inputs)
        logits_per_image = outputs.logits_per_image  # [1, n_concepts]
        probs = logits_per_image.softmax(dim=-1).squeeze(0).cpu().numpy()

        ranked = sorted(
            zip(candidate_concepts, probs), key=lambda p: p[1], reverse=True
        )
        top = ranked[: min(top_k, len(ranked))]
        scores = [ConceptScore(concept=c, score=float(s)) for c, s in top]
        return Prediction(scores=scores)

    def predict_with_heatmaps(
        self,
        image: Image.Image,
        candidate_concepts: list[str],
        top_k: int = 3,
        heatmap_top_n: int = 2,
    ) -> Prediction:
        """`predict`, then attach a region heatmap for the top-`heatmap_top_n`
        concepts so a differential call has comparable spatial evidence, not
        just a runner-up label.
        """
        pred = self.predict(image, candidate_concepts, top_k=top_k)
        for concept in pred.top_concepts[:heatmap_top_n]:
            try:
                pred.heatmaps[concept] = self.region_heatmap(image, concept)
            except Exception as exc:  # noqa: BLE001 - best-effort, see module docstring
                pred.heatmaps[concept] = None
                pred.heatmap_error = f"{type(exc).__name__}: {exc}"
        return pred

    def region_heatmap(self, image: Image.Image, concept: str) -> np.ndarray:
        """Gradient-based region-concept alignment map for a single concept.

        Grad-CAM over the vision tower's final patch-token layer: the
        gradient of the image-concept similarity w.r.t. patch tokens,
        weighted and summed, reshaped to the patch grid. Requires the
        underlying vision model to expose patch-level hidden states — if it
        doesn't, this raises and the caller records `heatmap_error` instead
        of crashing.
        """
        inputs = self.processor(
            text=[concept], images=image, return_tensors="pt", padding=True
        ).to(self.device)

        outputs = self.model(**inputs, output_hidden_states=True)
        patch_tokens = outputs.vision_model_output.hidden_states[-1][:, 1:, :]
        patch_tokens.retain_grad()

        similarity = outputs.logits_per_image.squeeze()
        self.model.zero_grad(set_to_none=True)
        similarity.backward(retain_graph=True)

        grads = patch_tokens.grad.squeeze(0)  # [n_patches, dim]
        weights = grads.mean(dim=-1)  # [n_patches]
        weights = weights.clamp(min=0)

        side = int(weights.numel() ** 0.5)
        heatmap = weights[: side * side].reshape(side, side).detach().cpu().numpy()
        heatmap -= heatmap.min()
        if heatmap.max() > 0:
            heatmap /= heatmap.max()
        return heatmap
