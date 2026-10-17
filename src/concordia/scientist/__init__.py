"""Single scientist interface and response persistence.

Experimental: a research side path, not part of the audit, verify and replay core.
"""

from concordia.scientist.adapters import (
    LlamaCppScientistAdapter,
    LocalRuntimeNotReadyError,
    OllamaScientistAdapter,
    OpenRouterScientistAdapter,
    ScientistModelAdapter,
)

__all__ = [
    "LlamaCppScientistAdapter",
    "LocalRuntimeNotReadyError",
    "OllamaScientistAdapter",
    "OpenRouterScientistAdapter",
    "ScientistModelAdapter",
]
