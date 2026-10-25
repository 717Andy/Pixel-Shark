import pytest

from pixelshark_device import AndroidScrcpy, IosScreen, PlaywrightDesktop, Pointer


def test_desktop_click_uses_the_page():
    clicks: list[tuple[float, float]] = []

    class Mouse:
        def click(self, x: float, y: float) -> None:
            clicks.append((x, y))

    class Page:
        mouse = Mouse()

        def screenshot(self, type: str = "png") -> bytes:  # noqa: A002 - Playwright's argument name
            assert type == "png"
            return b"png"

    screen = PlaywrightDesktop(Page())
    assert screen.capture() == b"png"
    screen.pointer(Pointer(kind="tap", x=3, y=4))
    assert clicks == [(3, 4)]


def test_mobile_backends_are_not_implemented():
    with pytest.raises(NotImplementedError):
        AndroidScrcpy().capture()
    with pytest.raises(NotImplementedError):
        IosScreen().pointer(Pointer(kind="tap", x=1, y=1))
