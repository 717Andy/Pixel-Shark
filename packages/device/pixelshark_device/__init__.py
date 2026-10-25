"""How Pixel Shark touches a screen.

Phase 0 ships a desktop backend that drives a real browser through Playwright.
Android (ADB and scrcpy) and iOS are named here so the orchestrator has a place
to grow, and they fail loudly instead of pretending to work.
"""

from pixelshark_device.screen import (
    AndroidScrcpy,
    IosScreen,
    PlaywrightDesktop,
    Pointer,
)

__all__ = ["AndroidScrcpy", "IosScreen", "PlaywrightDesktop", "Pointer"]
