"""Read a table from a screenshot.

:class:`VlmReader` sends a frame to a pluggable backend and returns a
schema-valid :class:`~pixelshark_schema.GameState` with a confidence on each
field. :class:`GroundTruthReader` still returns a state you already have, which
is what the orchestrator uses when it is not calling a model.

CI uses :class:`~pixelshark_perception.backends.MockBackend`. A Qwen-VL model
on a local NVIDIA GPU and a hosted chat API are selected with environment
variables. See ``docs/perception.md``.
"""

from pixelshark_perception.backends import (
    MockBackend,
    OpenAICompatibleBackend,
    OracleBackend,
    TransformersQwenBackend,
    VlmBackend,
    backend_from_env,
)
from pixelshark_perception.consistency import ConsistencyIssue, check_consistency
from pixelshark_perception.detector import PerSkinDetector, PerSkinDetectorTrainer
from pixelshark_perception.errors import PerceptionError
from pixelshark_perception.reader import GroundTruthReader, PerceptionResult, TableReader, VlmReader

__all__ = [
    "ConsistencyIssue",
    "GroundTruthReader",
    "MockBackend",
    "OpenAICompatibleBackend",
    "OracleBackend",
    "PerceptionError",
    "PerceptionResult",
    "PerSkinDetector",
    "PerSkinDetectorTrainer",
    "TableReader",
    "TransformersQwenBackend",
    "VlmBackend",
    "VlmReader",
    "backend_from_env",
    "check_consistency",
]
