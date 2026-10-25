"""Point at the on-screen button for a chosen action.

Phase 0 does not see pixels. It uses the bounding boxes the screenshot
generator saved (or a live DOM read) and returns the center of the matching
button. A later executor can search the frame when boxes are unavailable.
"""

from pixelshark_executor.click import ButtonExecutor, Click, locate

__all__ = ["ButtonExecutor", "Click", "locate"]
