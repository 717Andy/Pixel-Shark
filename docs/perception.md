# Reading the table from a screenshot

Pixel Shark is only for tables you are allowed to automate: this repository's
table, other self-hosted games, bot arenas that invite bots, and private games
where everyone has agreed. Do not point it at real-money sites. The longer
version is in the [README](../README.md).

This page is the perception step. A program looks at one picture of the table
and writes down the same game-state document the table itself uses. It does
not decide what to do, and it does not click.

You do not need a GPU to run the tests or to see what a report looks like.
You do need a GPU, or a hosted vision API, to get a real reading of a picture.

## The words

A **frame** is one screenshot, a PNG file.

A **vision-language model** (VLM) is a model that can look at a picture and
answer in text. Pixel Shark asks it for JSON, not a paragraph.

The **game state** is the JSON document from schema 1.0.0. Every fact the
model claims to have seen is a small object:

```json
{"value": "Ah", "confidence": 0.86}
```

`confidence` is a number from 0 to 1. It is the reader's own guess about how
sure it is. Ground truth from our table always uses 1, because the server
knows the cards. A model should use something lower when a digit is fuzzy.

`source` is `"perception"` on anything this package returns. The model is not
allowed to claim it is ground truth.

## What happens to one frame

1. The reader builds a prompt. The prompt explains the Pixel Shark layout,
   the card codes (`As`, `Td`, `9h`, `2c`; ten is `T`), and it pastes the
   JSON Schema the answer has to match.
2. The backend (mock, local model, or hosted API) returns text.
3. Repair pulls the JSON out of the text. It strips a markdown fence if the
   model added one, turns `10h` into `Th`, and wraps a bare number so it has
   a confidence. It does not invent the pot or the seats. If those are
   missing, the answer is rejected.
4. The schema either accepts the document or names what is wrong. On a
   failure the reader asks the model again, up to 3 times, and shows it the
   error. This is the retry.
5. Consistency checks then look at the document by itself:
   - the same card code must not appear twice
   - the street has to match the number of board cards (0, 3, 4, or 5)
   - the pot has to account for the bets (see below)
   - the button flags have to agree with the button seat
   - position names have to match that button
   - legal actions have to match the bets: check and call are never both
     legal, and a call amount has to equal the gap between the biggest bet
     and the actor's bet
6. When a check fails, the values stay as the model wrote them and the
   confidence on the disagreeing fields is cut in half (not below 0.05).
   The report lists the check codes so you can see why.

The pot rule matches this table. The number in the middle already includes
live bets, and the pot rows sum to that number. A read that instead reports
"collected chips + bets = total" is also accepted. If neither story works,
those chip fields are marked less sure.

## The backends

Set `PIXELSHARK_VLM` to pick one. The default is `mock`, which is what CI uses.
A mock does not look at the picture. It returns text you already wrote.

| `PIXELSHARK_VLM` | What it calls | Needs |
| --- | --- | --- |
| `mock` | Scripted text | Nothing. Optional `PIXELSHARK_VLM_MOCK_JSON` points at one JSON file. |
| `local` | An OpenAI-style server on your machine, meant for open weights such as Qwen2.5-VL | The server running. No key, unless you set one. |
| `qwen` | Qwen-VL inside this Python process, on the NVIDIA GPU | PyTorch and Transformers. See below. |
| `hosted` | A hosted chat API that accepts images the way OpenAI's API does | `PIXELSHARK_VLM_API_KEY` |
| `oracle` | Not a model. Eval only. Repeats the saved ground truth. | Nothing. |

Shared variables:

| Variable | Meaning | Default |
| --- | --- | --- |
| `PIXELSHARK_VLM_MODEL` | Model id | `Qwen/Qwen2.5-VL-7B-Instruct` for local and qwen, `gpt-4o` for hosted |
| `PIXELSHARK_VLM_BASE_URL` | Server root, including `/v1` | `http://127.0.0.1:8001/v1` for local, `https://api.openai.com/v1` for hosted |
| `PIXELSHARK_VLM_API_KEY` | Bearer token | `EMPTY` for local. Required for hosted. `OPENAI_API_KEY` is also accepted. |
| `PIXELSHARK_VLM_TIMEOUT` | Seconds to wait | 180 local, 120 hosted |
| `PIXELSHARK_VLM_MAX_TOKENS` | Reply length | 4096 |
| `PIXELSHARK_VLM_JSON_MODE` | Ask the server for a JSON object | off for local, on for hosted |
| `PIXELSHARK_QWEN_DEVICE` | `cuda` or `cpu` | `cuda` |
| `PIXELSHARK_QWEN_4BIT` | `1` to load the in-process model in 4-bit | off |

The table server uses port **8000**. Put a local model server on **8001** so
they do not collide.

`local` and `hosted` are the same code. Only the URL, the key, and the model
id change. Any host that implements `POST /v1/chat/completions` with an image
URL can be the hosted backend. OpenAI is the default. OpenRouter and similar
gateways work if you set `PIXELSHARK_VLM_BASE_URL` and the model id they expect.

## Check that the wiring works (no GPU)

From the repository root:

```bash
uv sync --all-packages --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Then build a report from the four checked-in screenshots. `--backend oracle`
ignores the pictures and returns the `state.json` that was saved with each
one. The score is perfect on purpose. Use it to see the files, not to judge a
model.

```bash
uv run pixelshark-perceive eval \
  --data examples/sample \
  --backend oracle \
  --out reports/perception
```

Open `reports/perception/report.md`. You should see 4 frames, exact match
100%, and a note that the held-out skin has no frames yet. `report.json` is
the same numbers for a program to read.

`reports/` is gitignored.

## Run a real eval on your NVIDIA laptop

The cloud agent that added this code did not have a GPU and did not download
weights. The commands below are what you run on the machine that does.

### 1. Make a dataset, including the held-out skin

`linen` is a light cloth look. It is not in `examples/sample`. The three dark
skins (`felt`, `midnight`, `broadcast`) are the ones a reader can "see" in the
checked-in set. Linen is held out so you can tell whether the reader only
memorized those three looks.

This needs Playwright's Chromium once:

```bash
uv run playwright install chromium
uv run pixelshark-datagen generate -n 12 -o /tmp/ps-eval --seed 7 --include-holdout
```

`-n 12` writes 12 frames in the default rotation. `--include-holdout` adds a
13th frame in linen. Use a larger `-n` when you want a stabler accuracy number.
The generator starts its own table, then shuts it down.

### 2a. Local open weights, as a server (the usual way)

Install [vLLM](https://docs.vllm.ai/) in its own environment. It is large, and
it is intentionally not in this repo's lockfile, so CI stays small. Then serve
a Qwen-VL checkpoint. The 7B Instruct model is a reasonable laptop GPU model
in bfloat16 if you have about 16 GB of VRAM. The 3B model is the smaller one.

```bash
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8001 --dtype bfloat16
```

Leave that running. In another terminal, from this repo:

```bash
export PIXELSHARK_VLM=local
export PIXELSHARK_VLM_BASE_URL=http://127.0.0.1:8001/v1
export PIXELSHARK_VLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
export PIXELSHARK_VLM_API_KEY=EMPTY

uv run pixelshark-perceive eval \
  --data /tmp/ps-eval \
  --holdout-skin linen \
  --out reports/perception \
  --log reports/reads
```

The first request will be slow while the model finishes loading. Later frames
are the number to look at in the latency line.

If that `vllm serve` command is rejected, the server build is older than the
model. Use the in-process path below, or upgrade vLLM. A llama.cpp server that
exposes the same `/v1/chat/completions` route is also a `local` backend. Point
`PIXELSHARK_VLM_BASE_URL` at it.

### 2b. Local open weights, inside this process

This loads Qwen-VL with Transformers on the GPU. It is the other local option.
The packages are not in the project lockfile:

```bash
uv pip install torch torchvision transformers accelerate qwen-vl-utils pillow
```

Add `bitsandbytes` too if you want 4-bit. Then:

```bash
export PIXELSHARK_VLM=qwen
export PIXELSHARK_VLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
export PIXELSHARK_QWEN_DEVICE=cuda
# export PIXELSHARK_QWEN_4BIT=1   # only if bitsandbytes is installed

uv run pixelshark-perceive eval \
  --data /tmp/ps-eval \
  --holdout-skin linen \
  --out reports/perception \
  --log reports/reads
```

The first run downloads the checkpoint from Hugging Face. That is several
gigabytes. CPU works if you set `PIXELSHARK_QWEN_DEVICE=cpu`, and it is too
slow to be the real eval.

If the GPU runs out of memory, switch the model id to
`Qwen/Qwen2.5-VL-3B-Instruct` or turn on 4-bit.

### 2c. A hosted API

```bash
export PIXELSHARK_VLM=hosted
export PIXELSHARK_VLM_API_KEY=sk-your-key
export PIXELSHARK_VLM_MODEL=gpt-4o

uv run pixelshark-perceive eval \
  --data /tmp/ps-eval \
  --holdout-skin linen \
  --out reports/perception \
  --log reports/reads
```

For another host:

```bash
export PIXELSHARK_VLM_BASE_URL=https://openrouter.ai/api/v1
export PIXELSHARK_VLM_MODEL=qwen/qwen2.5-vl-72b-instruct
```

Use whatever model id that host documents. Do not commit the key. The shell
export lasts until you close the terminal.

### Read one picture

```bash
uv run pixelshark-perceive read /tmp/ps-eval/0000/frame.png
```

The printed JSON is the perceived state. The line `no action taken` is there
so it is obvious this command does not play.

## How to read the report

`report.md` is the one to open first. `report.json` has the same counts plus
one row per frame.

| Column | What a "correct" answer means |
| --- | --- |
| cards | Board cards, plus hole cards whose faces were actually drawn. Card backs are not in this column. |
| cards_including_hidden | Those, plus the real hole cards even when the picture shows a back. A honest model that writes `null` for a back will miss this column. That is expected. |
| numbers | Blinds, ante, total pot, each pot amount, stacks, bets, button seat, actor seat. |
| positions | BTN, SB, BB, and the rest, per seat. |
| legal_actions | Each button: kind, call amount, min, max, sizing, all-in flag. |
| full_state_exact_match | All of the visible facts match on that frame, including names and status. Hidden hole-card codes are ignored. The "was this card face up?" flag is not ignored. |

Accuracy is correct divided by total. `n/a` means that column had nothing to
score (for example, no visible cards).

Latency is seconds per frame: mean, and the 50th and 95th percentiles. It
includes retries.

**Per skin** is the same table for `felt`, `midnight`, `broadcast`, and
`linen` separately.

**Seen skins** rolls up every skin except the holdout. **Held-out skin** is
linen by default (`--holdout-skin` changes it). If linen is worse than the
others, the reader is leaning on a look it has practice with. If they are
close, it is generalizing. One linen frame is only a smoke test. Generate
more before you trust the gap.

The frame table at the bottom lists check codes. `pot_mismatch`,
`duplicate_cards`, and `legal_actions` are the ones you will see most. A
`failure` means the model never produced schema-valid JSON. That frame counts
as wrong for every field.

The oracle report is not an accuracy number for a model. A real run will be
lower. Hidden cards in particular will hurt `cards_including_hidden` and will
not hurt `cards`.

## Watch a live table, and do not act

Start the table:

```bash
uv run pixelshark-table
```

Seat 0 is the bottom seat. The "Play seat 1" button sits you there too. In
another terminal, with a real backend exported the same way as the eval:

```bash
uv run playwright install chromium   # once
uv run pixelshark-perceive watch --url http://127.0.0.1:8000 --hero 0 --skin felt
```

The loop screenshots the page about once a second. When the read says the
actor is seat 0 and the hand is still betting, it prints the state. It prints
that turn once. It never moves the mouse. Stop it with Ctrl-C.

`--frames 5` takes five screenshots and exits. `--interval 0.5` polls faster.
The shot clock is 20 seconds by default. If you are seated and autoplay is on,
the server will check or fold for you when the clock runs out. Pause the bots
in the page header if you want the turn to stay on screen. Pausing also pauses
the clock.

This demo decides "our turn" from the model's read, not from a private API.
If the model names the wrong actor, it will print at the wrong time or not
at all.

## Saving reads for a later small model

`--log reports/reads` on `eval`, `read`, or `watch` writes:

```text
reports/reads/
  manifest.jsonl
  frames/0000.png
  reads/0000.json    # the model's JSON, the raw text, and the check codes
  truth/0000.json    # the ground truth, when the dataset had it
```

Each line of `manifest.jsonl` points at one frame, the perceived state, and
the skin. That is the pile a later training job can learn from.

The training hook exists and does not train:

```bash
uv run python -c "from pixelshark_perception import PerSkinDetectorTrainer; PerSkinDetectorTrainer().fit('reports/reads')"
```

It raises `NotImplementedError` and tells you how many frames it found, grouped
by skin. The next phase is the one that fits a fast detector per skin and
plugs it in behind the same `read` method.

## When something fails

**`The mock backend has no scripted answer`**
You left `PIXELSHARK_VLM` unset, or set it to `mock`, and there is no
`PIXELSHARK_VLM_MOCK_JSON` file. Tests build the mock in code. For a real
picture, set `PIXELSHARK_VLM` to `local`, `qwen`, or `hosted`.

**`the hosted backend needs PIXELSHARK_VLM_API_KEY`**
The key is missing. CI is supposed to fail this way rather than call out.

**`local backend could not be reached`**
Nothing is listening on port 8001, or the URL is missing `/v1`. The table on
port 8000 is not a vision model.

**`HTTP 401`**
The key was rejected. The error text is the server's message, not the key.

**`The local Qwen backend needs PyTorch`**
You set `PIXELSHARK_VLM=qwen` without the install line in section 2b.

**`could not load Qwen/...`**
The model id is wrong, the download failed, or the GPU cannot hold the
weights. Try the 3B model or 4-bit.

**`watch needs Playwright`**
Run `uv sync --all-packages --group dev` and `uv run playwright install chromium`.

**`could not reach the table`**
Start `uv run pixelshark-table` first. Watch does not start it for you.

**A frame fails validation three times**
The model is not returning the schema. Look at the error in the report's
`failure` field. Raising `--attempts` rarely helps if the model is ignoring
the prompt. A smaller model sometimes does better through the `local` server
than in-process, because the server's template matches the checkpoint.

## What is left for later

The reader is the whole perception step for this phase. It does not track a
hand across frames, it does not choose an action, and it does not click. The
orchestrator still runs on ground truth until you pass it a `VlmReader`.
Detector training is the stub above, on purpose.
