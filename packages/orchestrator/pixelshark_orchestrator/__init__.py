"""One decision, from a frame to a click.

The loop is perceive, track, choose, style, locate. Phase 0 runs it with a
ground-truth reader and the scripted baseline. Nothing in this package calls
a model.
"""

from pixelshark_orchestrator.loop import AgentLoop, StepResult

__all__ = ["AgentLoop", "StepResult"]
