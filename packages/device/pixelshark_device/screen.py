"""Screen backends. Only the desktop one is implemented."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Pointer:
    """A click or tap in viewport pixels."""

    kind: str
    x: float
    y: float


class Screen(Protocol):
    def capture(self) -> bytes:
        """PNG bytes of the current frame."""

    def pointer(self, action: Pointer) -> None:
        """Click or tap at the given point."""


class PlaywrightDesktop:
    """Drive a Playwright ``Page``. The page is created by the caller.

    Datagen uses this to screenshot the self-hosted table. A later agent uses
    the same methods to click buttons it has located.
    """

    def __init__(self, page: object) -> None:
        self._page = page

    def capture(self) -> bytes:
        screenshot = self._page.screenshot
        data = screenshot(type="png")
        if not isinstance(data, bytes):
            raise TypeError("Playwright screenshot did not return bytes")
        return data

    def pointer(self, action: Pointer) -> None:
        if action.kind not in ("click", "tap"):
            raise ValueError(f"unsupported pointer action {action.kind!r}")
        mouse = self._page.mouse
        mouse.click(action.x, action.y)


class AndroidScrcpy:
    """Placeholder for an ADB plus scrcpy backend.

    A later phase will capture with ``adb exec-out screencap`` (or a scrcpy
    video socket) and tap with ``adb shell input tap``. It is not wired up yet.
    """

    def capture(self) -> bytes:
        raise NotImplementedError(
            "Android capture via ADB/scrcpy is a later phase. "
            "Use PlaywrightDesktop against the self-hosted table."
        )

    def pointer(self, action: Pointer) -> None:
        raise NotImplementedError(
            "Android tap via ADB is a later phase. "
            "Use PlaywrightDesktop against the self-hosted table."
        )


class IosScreen:
    """Placeholder for an iOS backend (a WebDriverAgent-style tap and screenshot).

    Not implemented. Phase 0 only drives the desktop browser.
    """

    def capture(self) -> bytes:
        raise NotImplementedError(
            "iOS capture is a later phase. Use PlaywrightDesktop against the self-hosted table."
        )

    def pointer(self, action: Pointer) -> None:
        raise NotImplementedError(
            "iOS tap is a later phase. Use PlaywrightDesktop against the self-hosted table."
        )
