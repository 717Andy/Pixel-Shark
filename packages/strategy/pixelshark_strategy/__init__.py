"""Choose an action from a game state.

The phase-0 baseline is the scripted bot in ``pixelshark_sim``. OpenSpiel and
CFR will implement :class:`Strategy` later and return the same
:class:`pixelshark_schema.Decision`.
"""

from pixelshark_strategy.policy import ScriptedStrategy, Strategy

__all__ = ["ScriptedStrategy", "Strategy"]
