"""Watch a live table and print the read when it is our turn.

Nothing in this module clicks. The executor is a later phase. "Our turn" is
decided from the read itself: the actor seat equals the hero seat and the
hand is in a betting phase.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from typing import Protocol

from pixelshark_perception.errors import PerceptionError
from pixelshark_perception.reader import PerceptionResult, VlmReader
from pixelshark_schema import GameState


class Capturer(Protocol):
    def capture(self) -> bytes:
        """PNG (or other image) bytes of the current screen."""


def iter_our_turns(
    screen: Capturer,
    reader: VlmReader,
    hero_seat: int,
    *,
    frames: int | None = None,
    interval_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    on_error: Callable[[PerceptionError], None] | None = None,
) -> Iterator[PerceptionResult]:
    """Yield one result each time a new turn for ``hero_seat`` is read.

    ``frames`` is how many screenshots to take. ``None`` keeps going until the
    caller stops the loop. The same hand and street is printed once, so a
    paused table does not flood the terminal.
    """

    seen: set[tuple[str, str, int | None]] = set()
    taken = 0
    while frames is None or taken < frames:
        image = screen.capture()
        taken += 1
        try:
            result = reader.read_detail(image)
        except PerceptionError as exc:
            if on_error is not None:
                on_error(exc)
        else:
            state = result.state
            key = (state.hand_id, state.street.value, state.actor_seat.value)
            ours = state.hand_phase.value == "betting" and state.actor_seat.value == hero_seat
            if ours and key not in seen:
                seen.add(key)
                yield result
        if interval_s > 0 and (frames is None or taken < frames):
            sleep(interval_s)


def format_turn(result: PerceptionResult, *, heading: str = "our turn") -> str:
    """A few lines a person can scan, followed by a reminder that we do not act."""

    state = result.state
    lines = [
        (
            f"{heading}  hand={state.hand_id}  "
            f"street={state.street.value} ({state.street.confidence:.2f})  "
            f"pot={state.total_pot.value} ({state.total_pot.confidence:.2f})"
        ),
        f"actor seat {state.actor_seat.value}  button seat {state.button_seat.value}",
        "board: " + (" ".join(card.value or "??" for card in state.board) or "(none)"),
    ]
    for seat in state.seats:
        cards = " ".join(card.value or "??" for card in seat.hole_cards) or "(no cards)"
        position = seat.position.value or "-"
        lines.append(
            f"  seat {seat.seat} {seat.name.value} {position} "
            f"stack {seat.stack.value} bet {seat.bet.value} {seat.status.value} [{cards}]"
        )
    kinds = ", ".join(action.kind for action in state.legal_actions) or "(none)"
    lines.append(f"legal: {kinds}")
    if result.issues:
        lines.append("checks: " + "; ".join(issue.code for issue in result.issues))
    lines.append("no action taken")
    return "\n".join(lines)


def format_state(state: GameState) -> str:
    """The perceived document, pretty-printed."""

    return json.dumps(state.model_dump(mode="json"), indent=2)


def run_table_watch(
    *,
    base_url: str,
    hero_seat: int,
    reader: VlmReader,
    skin: str = "felt",
    frames: int | None = None,
    interval_s: float = 1.0,
    on_turn: Callable[[PerceptionResult], None],
    on_error: Callable[[PerceptionError], None] | None = None,
) -> None:
    """Open the table in Chromium, sit ``hero_seat``, and print our turns.

    Playwright is imported here so the rest of the package imports without a
    browser. The table must already be running. This function never clicks.
    """

    try:
        from playwright.sync_api import sync_playwright

        from pixelshark_device import PlaywrightDesktop
    except ImportError as exc:
        raise PerceptionError(
            "watch needs Playwright and the device package. From the repo root run "
            "`uv sync --all-packages --group dev` and `uv run playwright install chromium`."
        ) from exc

    url = base_url.rstrip("/")
    table_id = _session_table(url)
    _post(url, f"/api/tables/{table_id}/hero", {"seat": hero_seat})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        try:
            page.goto(f"{url}/?table={table_id}&skin={skin}", wait_until="domcontentloaded")
            page.wait_for_function("() => document.body.dataset.ready === 'true'", timeout=15_000)
            screen = PlaywrightDesktop(page)
            for result in iter_our_turns(
                screen,
                reader,
                hero_seat,
                frames=frames,
                interval_s=interval_s,
                on_error=on_error,
            ):
                on_turn(result)
        finally:
            browser.close()


def _session_table(base_url: str) -> str:
    payload = _request("GET", f"{base_url}/api/session")
    table_id = payload.get("table_id")
    if not isinstance(table_id, str) or not table_id:
        raise PerceptionError(f"the table at {base_url} did not return a table id")
    return table_id


def _post(base_url: str, path: str, body: dict[str, object]) -> None:
    _request("POST", f"{base_url}{path}", body)


def _request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
    except urllib.error.URLError as exc:
        raise PerceptionError(f"could not reach the table at {url}: {exc.reason}") from exc
    if not raw:
        return {}
    decoded = json.loads(raw.decode())
    if not isinstance(decoded, dict):
        raise PerceptionError(f"the table at {url} did not return an object")
    return decoded
