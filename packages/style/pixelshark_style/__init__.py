"""Turn a strategic decision into how it should be performed.

Timing, sizing jitter, and misclick avoidance live here later. Phase 0 only
attaches a delay so the orchestrator has a real object to pass downstream.
"""

from pixelshark_style.style import HumanPace, IdentityStyle, Style, StyledAction

__all__ = ["HumanPace", "IdentityStyle", "StyledAction", "Style"]
