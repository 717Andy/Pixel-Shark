# Pixel Shark

Pixel Shark is a research project for a screen-driven poker agent. It looks at
the table the way a person does — a screenshot — and acts with the mouse or a
tap. The idea is in the same family as a "digital" robot that uses a computer
by seeing the screen, not by calling a private poker API.

Phase 0 is the foundation: a self-hosted no-limit hold'em table, a written-down
description of a game state, and a tool that saves screenshots of that table
together with the true state of the hand. Perception can now read a screenshot
into that same description. The tests use a stand-in, so nothing here downloads
a model. How to run a real one on your own GPU is in
[docs/perception.md](docs/perception.md).

## Where this is allowed to play

Use Pixel Shark only on games you are allowed to automate:

- this repository's table, on your own machine
- other open-source engines and self-hosted tables
- bot arenas that invite bots (Slumbot is the usual example)
- private games where every player has agreed

Do not point it at real-money sites, or at play-money / points sites whose
rules ban bots. Those sites are out of scope for this project. PokerTH is
discussed in [docs/pokerth.md](docs/pokerth.md) only as a possible later
self-hosted client, not as a target on the public `pokerth.net` lobby.

## What is in the repo

The code is a uv workspace. Each directory under `packages/` is one layer.
Most of them are interfaces plus a small baseline. The table and the
simulator are the parts that actually play cards.

| Package | What it does today |
| --- | --- |
| `packages/sim` | No-limit hold'em for 2–9 seats, on top of [PokerKit](https://pokerkit.readthedocs.io/). Scripted and random bots. |
| `packages/schema` | The versioned game-state document (Pydantic and a checked-in JSON Schema). |
| `packages/table` | HTTP + WebSocket API and the browser UI, with three skins. |
| `packages/datagen` | Headless screenshots, bounding boxes, and ground truth. |
| `packages/device` | Desktop clicks and screenshots through Playwright. Android (ADB/scrcpy) and iOS are named and not implemented. |
| `packages/perception` | Reads a frame into the schema. A vision-language model is the reader. CI uses a mock. A fast per-skin detector is only a stub. |
| `packages/tracker` | Will keep a stable belief across frames. Today it passes one observation through. |
| `packages/strategy` | Will be OpenSpiel / CFR. Today it calls the scripted bot. |
| `packages/style` | Will turn a chosen action into timing and small human-looking adjustments. Today it only attaches a delay. |
| `packages/executor` | Finds the on-screen button for an action from bounding boxes and returns the click point. |
| `packages/orchestrator` | One cycle: read, track, choose, style, locate. It still uses ground truth unless you pass it a perception reader. |

```text
screenshot  ->  perception  ->  tracker  ->  strategy  ->  style  ->  executor  ->  click
                     ^
                     |
               packages/table  (ground truth, until a model exists)
```

## Requirements

- Python 3.11 or newer. 3.12 is what CI uses.
- [uv](https://docs.astral.sh/uv/) for installs. You do not need poetry.
- Docker, only if you want `docker compose up` instead of running Python yourself.
- Playwright's Chromium, only if you regenerate screenshots.

## Run the table

From the repository root:

```bash
uv sync --all-packages --group dev
uv run pixelshark-table
```

Then open <http://127.0.0.1:8000>.

Six bots play no-limit hold'em on their own (blinds 50/100, stacks 10,000).
Use the header to change the skin, show or hide cards, sit in seat 1, or pause
the bots. On your turn the buttons at the bottom are live. `F` folds. `C`
checks or calls.

"Raise to 300" means your total bet on this street becomes 300. It does not
mean "300 more". That is how the rules engine counts chips, and the buttons
use the same number.

The server listens on `127.0.0.1` unless you set `PIXELSHARK_HOST`. Useful
variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PIXELSHARK_HOST` | `127.0.0.1` | Bind address. Compose sets `0.0.0.0`. |
| `PIXELSHARK_PORT` | `8000` | Port. |
| `PIXELSHARK_SEATS` | `6` | 2–9. |
| `PIXELSHARK_SB` / `PIXELSHARK_BB` | `50` / `100` | Blinds. |
| `PIXELSHARK_STACK` | `10000` | Starting stack, also the rebuy. |
| `PIXELSHARK_SEED` | `1` | Deals and the scripted bot. |
| `PIXELSHARK_AUTOPLAY` | `1` | Bots act, and the shot clock is enforced. |
| `PIXELSHARK_SHOT_CLOCK_MS` | `20000` | How long a human seat gets before check-or-fold. |
| `PIXELSHARK_HERO_SEAT` | empty | Set to `0` if you want to be in the hand at startup. |
| `PIXELSHARK_REVEAL` | `showdown` | `showdown`, `hero`, or `all`. |

### Docker

```bash
docker compose up --build
```

Same site on port 8000. The image is only the table. It does not download a
browser or a model.

## The game-state document

Every snapshot is schema **1.0.0**. The table returns it from
`GET /api/tables/{id}/state`. The JSON Schema file is
[`packages/schema/pixelshark_schema/game_state.schema.json`](packages/schema/pixelshark_schema/game_state.schema.json)
and `GET /api/schema` serves the same document.

Observed values are wrapped so a model can be unsure later:

```json
{
  "schema_version": "1.0.0",
  "source": "ground_truth",
  "street": {"value": "flop", "confidence": 1.0},
  "button_seat": {"value": 0, "confidence": 1.0},
  "board": [{"value": "Ah", "confidence": 1.0}],
  "total_pot": {"value": 450, "confidence": 1.0},
  "seats": []
}
```

Ground truth from this table always uses confidence `1.0`. Hole-card codes are
always filled in, even when the picture shows a card back. `hole_cards_shown`
is what the UI drew. A future perception model should use the same schema,
with a lower confidence and `null` cards when it did not read them, and set
`source` to `"perception"`.

Card codes are rank then suit: `As`, `Td`, `9h`, `2c`. Ten is `T`.

`legal_actions` lists fold, check, call, bet, and raise, including the call
amount and the min/max "to" amount for a bet or raise. `sizing` is the row of
buttons (min, 1/3 pot, 1/2 pot, 2/3 pot, pot, all-in) that fall inside that
range. `timers` is the shot clock.

Seats stay put. The button moves clockwise. Heads-up, the button posts the
small blind and acts first before the flop. With three or more players the
first preflop actor is the seat after the big blind.

### HTTP, briefly

| Request | What it does |
| --- | --- |
| `GET /health` | Liveness. |
| `GET /api/session` | The default table (`home`) and its state. |
| `POST /api/tables` | Open another table. Body can set seats, blinds, seed, hero, bots, reveal. |
| `GET /api/tables/{id}/state` | Ground truth only. |
| `POST /api/tables/{id}/actions` | `{"seat": 0, "kind": "raise", "to_amount": 300}`. |
| `POST /api/tables/{id}/step` | One bot action, or deal the next hand if the current one is over. |
| `POST /api/tables/{id}/hero` | `{"seat": 0}` to sit, `{"seat": null}` to watch. |
| `POST /api/tables/{id}/autoplay` | `{"enabled": false}` pauses bots and the shot clock. |
| `POST /api/tables/{id}/reveal` | `{"mode": "all"}`. |
| `WS /api/tables/{id}/ws` | The same JSON, pushed after each change. |

An illegal action is HTTP 409.

## Screenshots

`examples/sample/` is a small set already generated so you can see the files
without installing a browser. Each sample directory has:

- `frame.png` — the viewport, plus a little brightness and grain
- `state.json` — ground truth for that frame
- `boxes.json` — pixel boxes for cards, chip piles, and buttons
- `meta.json` — skin, viewport, reveal mode, noise settings

Boxes are viewport pixels at scale 1. The noise does not move anything, so a
box from `boxes.json` still covers the same card in `frame.png`.

Regenerate or extend it with:

```bash
uv run playwright install chromium
uv run pixelshark-datagen generate -n 4 -o examples/sample --seed 7
```

The command starts its own table server, deals to a chosen street, screenshots
that street, and shuts the server down. Pass `--base-url http://127.0.0.1:8000`
to use a server you already started. Skins in the default rotation are
`felt`, `midnight`, and `broadcast`. `--include-holdout` adds one extra frame
in `linen`, a light skin the perception eval scores separately. The table UI
has that skin too: it is the fourth entry in the skin menu.

## Reading a screenshot

`pixelshark-perceive` turns a frame into the same game-state document the table
emits, with a confidence on each field. It does not click. The short version,
including how to score `examples/sample` with no GPU and how to point it at a
Qwen-VL model on an NVIDIA laptop, is [docs/perception.md](docs/perception.md).

```bash
uv run pixelshark-perceive eval --data examples/sample --backend oracle --out reports/perception
```

`oracle` repeats the saved ground truth so you can see a perfect report. It is
not a vision model.

## Tests and lint

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

CI on GitHub Actions runs those three. Pre-commit runs ruff as well:

```bash
uv run pre-commit install
```

## PokerTH

A current PokerTH dedicated server can be a later cross-platform target
(desktop, Android, iOS, all speaking one protocol, no real-money play). It is
not started by `docker compose up`. The short version: the easy Docker image
installs Ubuntu's `pokerth-server` package, which is older than the 2.1.10
server current clients accept, and building 2.1.10 inside Compose means a full
Qt 6 compile on every cold start. Details and the next build step are in
[docs/pokerth.md](docs/pokerth.md).

## What this phase does not do

- The vision reader is wired up, but this repository does not download weights
  and CI never calls a model. There is no CFR or OpenSpiel agent yet, and no
  Android or iOS device control.
- The live watch loop prints a state when it thinks it is your turn. It does
  not choose or click an action.
- Per-skin detector training is a stub. The read log is the input it will use.
- No login, no accounts, no hardening. It is a research server. Keep it on
  localhost unless you know who can reach the port.
- Bots rebuy to the starting stack between hands so a table does not die when
  someone busts. Turn that off with `"rebuy": false` on `POST /api/tables` if
  you want stacks to stay busted.
