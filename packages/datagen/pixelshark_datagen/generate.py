"""Drive the table headlessly and write frame / state / box triples.

The dev server is started with autoplay off so a frame cannot change between
the screenshot and the state download. Noise is applied after the screenshot
and does not shift the boxes.
"""

from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from pixelshark_datagen.noise import apply_noise
from pixelshark_schema import GameState

_BOX_JS = """
() => {
  const round = (value) => Math.round(value * 100) / 100;
  return [...document.querySelectorAll("[data-bbox]")].map((el) => {
    const rect = el.getBoundingClientRect();
    const attrs = {};
    for (const [key, value] of Object.entries(el.dataset)) {
      if (key === "bbox") continue;
      attrs[key] = value;
    }
    return {
      label: el.dataset.bbox,
      x: round(rect.x),
      y: round(rect.y),
      width: round(rect.width),
      height: round(rect.height),
      attrs,
    };
  }).filter((box) => box.width > 0 && box.height > 0);
}
"""

# Linen is a light skin kept out of the default rotation. Perception eval
# scores it separately to see whether a reader generalizes past the three
# skins in examples/sample.
HOLDOUT_SKIN = "linen"

# A small fixed roster so `examples/sample` covers the skins, a phone-sized
# viewport, face-up cards, and a frame where the hero is the one to act.
_PLANS: tuple[dict[str, Any], ...] = (
    {
        "skin": "felt",
        "width": 1280,
        "height": 720,
        "reveal": "all",
        "street": "flop",
        "hero": None,
        "wait_hero": False,
    },
    {
        "skin": "midnight",
        "width": 1440,
        "height": 900,
        "reveal": "showdown",
        "street": "turn",
        "hero": 0,
        "wait_hero": True,
    },
    {
        "skin": "broadcast",
        "width": 1024,
        "height": 768,
        "reveal": "all",
        "street": "preflop",
        "hero": 0,
        "wait_hero": True,
    },
    {
        "skin": "midnight",
        "width": 390,
        "height": 844,
        "reveal": "hero",
        "street": "river",
        "hero": None,
        "wait_hero": False,
    },
)

_HOLDOUT_PLAN: dict[str, Any] = {
    "skin": HOLDOUT_SKIN,
    "width": 1280,
    "height": 800,
    "reveal": "all",
    "street": "turn",
    "hero": 0,
    "wait_hero": True,
}


def plans_for(*, count: int, include_holdout: bool = False) -> list[dict[str, Any]]:
    """The capture plan for each sample. Holdout adds one linen frame at the end."""

    if count < 1:
        raise ValueError("count must be at least 1")
    sequence = [_PLANS[index % len(_PLANS)] for index in range(count)]
    if include_holdout:
        sequence.append(_HOLDOUT_PLAN)
    return sequence


def generate_dataset(
    *,
    count: int,
    out: Path,
    seed: int = 7,
    base_url: str | None = None,
    seats: int = 6,
    include_holdout: bool = False,
) -> Path:
    """Write ``count`` samples under ``out`` and return that directory.

    ``include_holdout`` appends one extra frame in the linen skin after those
    samples. The default rotation is unchanged.
    """

    sequence = plans_for(count=count, include_holdout=include_holdout)
    out.mkdir(parents=True, exist_ok=True)
    own_server = base_url is None
    server: subprocess.Popen[str] | None = None
    if own_server:
        base_url, server = _start_server()
    assert base_url is not None
    try:
        from playwright.sync_api import sync_playwright

        from pixelshark_device import PlaywrightDesktop

        samples: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for index, plan in enumerate(sequence):
                    sample_id = f"{index:04d}"
                    meta = _capture_one(
                        browser=browser,
                        base_url=base_url,
                        out=out / sample_id,
                        sample_id=sample_id,
                        seed=seed + index,
                        seats=seats,
                        plan=plan,
                        screen_factory=PlaywrightDesktop,
                    )
                    samples.append(meta)
            finally:
                browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    manifest = {
        "schema_version": "1.0.0",
        "generator": "pixelshark-datagen",
        "seed": seed,
        "count": len(sequence),
        "samples": samples,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out


def _capture_one(
    *,
    browser: Any,
    base_url: str,
    out: Path,
    sample_id: str,
    seed: int,
    seats: int,
    plan: dict[str, Any],
    screen_factory: type,
) -> dict[str, Any]:
    hero = plan["hero"]
    bot_seats = [seat for seat in range(seats) if seat != hero]
    created = _request(
        "POST",
        f"{base_url}/api/tables",
        {
            "seats": seats,
            "hero_seat": hero,
            "bot_seats": bot_seats,
            "button_seat": 0,
            "seed": seed,
            "reveal": plan["reveal"],
            "autoplay": False,
            "bot_policy": "scripted",
            "starting_stack": 10_000,
            "small_blind": 50,
            "big_blind": 100,
        },
    )
    table_id = created["table_id"]
    state = _advance(
        base_url,
        table_id,
        street=plan["street"],
        hero=hero,
        wait_hero=bool(plan["wait_hero"]),
    )
    hand_id = state["hand_id"]
    context = browser.new_context(
        viewport={"width": plan["width"], "height": plan["height"]},
        device_scale_factor=1,
    )
    page = context.new_page()
    try:
        page.goto(
            f"{base_url}/?table={table_id}&skin={plan['skin']}",
            wait_until="domcontentloaded",
        )
        page.wait_for_function(
            """(handId) =>
                document.body.dataset.ready === 'true' &&
                document.body.dataset.handId === handId""",
            arg=hand_id,
            timeout=15_000,
        )
        page.wait_for_timeout(40)
        raw = screen_factory(page).capture()
        boxes = page.evaluate(_BOX_JS)
    finally:
        context.close()
    labels = {box["label"] for box in boxes}
    missing = {"card", "chips", "button"} - labels
    if missing:
        raise RuntimeError(f"sample {sample_id} is missing boxes for {sorted(missing)}")
    # Re-read ground truth after the screenshot. Autoplay is off, so it matches the frame.
    state = _request("GET", f"{base_url}/api/tables/{table_id}/state")
    GameState.model_validate(state)
    rng = random.Random(f"{seed}:noise")
    image = Image.open(BytesIO(raw))
    noisy, noise = apply_noise(image, rng)
    out.mkdir(parents=True, exist_ok=True)
    noisy.save(out / "frame.png")
    (out / "state.json").write_text(json.dumps(state, indent=2) + "\n")
    (out / "boxes.json").write_text(
        json.dumps(
            {"width": plan["width"], "height": plan["height"], "boxes": boxes},
            indent=2,
        )
        + "\n"
    )
    meta = {
        "id": sample_id,
        "table_id": table_id,
        "hand_id": state["hand_id"],
        "street": state["street"]["value"],
        "skin": plan["skin"],
        "reveal": plan["reveal"],
        "viewport": [plan["width"], plan["height"]],
        "seed": seed,
        "noise": noise,
        "hero_seat": hero,
        "wait_hero": plan["wait_hero"],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def _advance(
    base_url: str,
    table_id: str,
    *,
    street: str,
    hero: int | None,
    wait_hero: bool,
) -> dict[str, Any]:
    for _ in range(160):
        state = _request("GET", f"{base_url}/api/tables/{table_id}/state")
        phase = state["hand_phase"]["value"]
        actor = state["actor_seat"]["value"]
        if phase == "betting" and state["street"]["value"] == street:
            if not wait_hero or actor == hero:
                return state
        if phase == "complete":
            _request("POST", f"{base_url}/api/tables/{table_id}/next")
            continue
        if hero is not None and actor == hero:
            _act_passive(base_url, table_id, state)
            continue
        try:
            _request("POST", f"{base_url}/api/tables/{table_id}/step")
        except urllib.error.HTTPError as exc:
            if exc.code != 409:
                raise
            latest = _request("GET", f"{base_url}/api/tables/{table_id}/state")
            _act_passive(base_url, table_id, latest)
    raise RuntimeError(f"could not reach {street} on {table_id}")


def _act_passive(base_url: str, table_id: str, state: dict[str, Any]) -> None:
    kinds = {action["kind"]: action for action in state["legal_actions"]}
    seat = state["actor_seat"]["value"]
    if "check" in kinds:
        body = {"seat": seat, "kind": "check"}
    elif "call" in kinds:
        body = {"seat": seat, "kind": "call"}
    else:
        body = {"seat": seat, "kind": "fold"}
    _request("POST", f"{base_url}/api/tables/{table_id}/actions", body)


def _start_server() -> tuple[str, subprocess.Popen[str]]:
    port = _free_port()
    env = os.environ.copy()
    env["PIXELSHARK_CREATE_DEFAULT"] = "0"
    env["PIXELSHARK_AUTOPLAY"] = "0"
    env["PIXELSHARK_HOST"] = "127.0.0.1"
    env["PIXELSHARK_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, "-m", "pixelshark_table", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(f"table server exited early:\n{output}")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=0.5) as response:
                if response.status == 200:
                    return url, process
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError(f"table server did not become healthy: {last_error}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
    return json.loads(body.decode()) if body else {}
