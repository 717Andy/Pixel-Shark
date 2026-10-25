"""Keep a stable belief across frames.

A later tracker will smooth seat identity, remember hole cards that were seen
and then covered, and drop impossible jumps (a pot that shrinks mid-street).
Phase 0 passes each observation through unchanged.
"""

from pixelshark_tracker.tracker import PassthroughTracker, Tracker

__all__ = ["PassthroughTracker", "Tracker"]
