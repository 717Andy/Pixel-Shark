"""Turn a model's loose JSON into a document the schema can accept.

Models wrap answers in markdown, write ``10h`` instead of ``Th``, and sometimes
emit a bare number where the schema wants ``{"value": number, "confidence": ...}``.
This module fixes that kind of slip. It does not invent the pot, the board, or
the seats. If those are missing, validation fails and the reader asks again.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pixelshark_perception.errors import PerceptionError

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_SUIT_WORDS = {
    "c": "c",
    "d": "d",
    "h": "h",
    "s": "s",
    "♣": "c",
    "♦": "d",
    "♥": "h",
    "♠": "s",
    "clubs": "c",
    "club": "c",
    "diamonds": "d",
    "diamond": "d",
    "hearts": "h",
    "heart": "h",
    "spades": "s",
    "spade": "s",
}
_RANK_WORDS = {
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
    "10": "T",
    "t": "T",
    "j": "J",
    "q": "Q",
    "k": "K",
    "a": "A",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "T",
    "jack": "J",
    "queen": "Q",
    "king": "K",
    "ace": "A",
}
_CARD = re.compile(r"^[2-9TJQKA][cdhs]$")

_POSITIONS = {
    "btn": "BTN",
    "button": "BTN",
    "dealer": "BTN",
    "sb": "SB",
    "small blind": "SB",
    "smallblind": "SB",
    "bb": "BB",
    "big blind": "BB",
    "bigblind": "BB",
    "utg": "UTG",
    "utg+1": "UTG+1",
    "utg1": "UTG+1",
    "mp": "MP",
    "lj": "LJ",
    "hj": "HJ",
    "co": "CO",
    "cutoff": "CO",
    "cut-off": "CO",
}
_STREETS = {
    "preflop": "preflop",
    "pre-flop": "preflop",
    "pre flop": "preflop",
    "flop": "flop",
    "turn": "turn",
    "river": "river",
}
_PHASES = {
    "betting": "betting",
    "complete": "complete",
    "completed": "complete",
    "finished": "complete",
    "showdown": "complete",
    "over": "complete",
}
_STATUSES = {
    "active": "active",
    "folded": "folded",
    "fold": "folded",
    "all_in": "all_in",
    "all-in": "all_in",
    "all in": "all_in",
    "allin": "all_in",
    "sitting_out": "sitting_out",
    "sitting out": "sitting_out",
    "sit out": "sitting_out",
    "out": "sitting_out",
}
_KINDS = {"fold": "fold", "check": "check", "call": "call", "bet": "bet", "raise": "raise"}
_SIZING = {
    "min": "min",
    "minimum": "min",
    "1/3": "1/3 pot",
    "1/3 pot": "1/3 pot",
    "third": "1/3 pot",
    "1/2": "1/2 pot",
    "1/2 pot": "1/2 pot",
    "half": "1/2 pot",
    "half pot": "1/2 pot",
    "2/3": "2/3 pot",
    "2/3 pot": "2/3 pot",
    "pot": "pot",
    "all-in": "all-in",
    "all in": "all-in",
    "allin": "all-in",
}
_NESTED_KEYS = ("game_state", "state", "snapshot", "result")


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply."""

    stripped = text.strip()
    fenced = _FENCE.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise PerceptionError("the model reply had no JSON object") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PerceptionError(f"the model reply was not valid JSON: {exc}") from exc
    if isinstance(value, list) and value and isinstance(value[0], dict):
        value = value[0]
    if not isinstance(value, dict):
        raise PerceptionError("the model reply was not a JSON object")
    return _unwrap(value)


def repair_document(data: dict[str, Any], *, default_confidence: float = 0.8) -> dict[str, Any]:
    """Normalize one decoded object. Missing felt facts stay missing."""

    confidence = _unit(default_confidence, 0.8)
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source": "perception",
        "table_id": _text(data.get("table_id")) or "perceived",
        "hand_id": _text(data.get("hand_id")) or "perceived-h1",
        "variant": "NLHE",
        "hand_number": _int_obs(data.get("hand_number", {"value": 1}), confidence, fallback=1),
        "ante": _int_obs(data["ante"], confidence) if "ante" in data else _int_obs(0, 0.2),
        "board": [_card_obs(card, confidence) for card in _as_list(data.get("board"))],
        "pots": [
            _pot(pot, confidence) for pot in _as_list(data.get("pots")) if isinstance(pot, dict)
        ],
        "legal_actions": [
            action
            for action in (_legal(item, confidence) for item in _as_list(data.get("legal_actions")))
            if action is not None
        ],
        "timers": _timers(data.get("timers"), confidence),
        "hero_seat": _optional_seat(data.get("hero_seat")),
        "reveal": data.get("reveal")
        if data.get("reveal") in ("all", "hero", "showdown")
        else "showdown",
        "autoplay": bool(data.get("autoplay", False)),
        "last_action": _text(data.get("last_action")) or None,
    }
    for key, coerce in (
        ("small_blind", _plain_int),
        ("big_blind", _plain_int),
        ("total_pot", _plain_int),
        ("button_seat", _plain_int),
    ):
        if key in data:
            document[key] = _int_obs(data[key], confidence, coerce=coerce)
    if "street" in data:
        document["street"] = _enum_obs(data["street"], _STREETS, confidence)
    if "hand_phase" in data:
        document["hand_phase"] = _enum_obs(data["hand_phase"], _PHASES, confidence)
    if "actor_seat" in data:
        document["actor_seat"] = _actor(data["actor_seat"], confidence)
    if "seats" in data:
        document["seats"] = [
            _seat(seat, confidence)
            for seat in _as_list(data.get("seats"))
            if isinstance(seat, dict)
        ]
    return document


def normalize_card(value: Any) -> str | None:
    """Return a schema card code, or None when the card is unknown."""

    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.lower() in {"", "null", "none", "unknown", "?", "??", "back", "facedown", "face down"}:
        return None
    text = text.replace("10", "T")
    if len(text) == 2 and text[0] in "23456789TJQKA" and text[1] in "cdhsCDHS♣♦♥♠":
        suit = _SUIT_WORDS[text[1].lower()] if text[1].isalpha() else _SUIT_WORDS[text[1]]
        code = f"{text[0].upper()}{suit}"
        return code if _CARD.fullmatch(code) else None
    lowered = text.lower().replace("_", " ").replace("-", " ")
    lowered = re.sub(r"\s+", " ", lowered).strip()
    if " of " in lowered:
        rank_word, _, suit_word = lowered.partition(" of ")
        rank = _RANK_WORDS.get(rank_word.strip())
        suit = _SUIT_WORDS.get(suit_word.strip())
        if rank and suit:
            return f"{rank}{suit}"
    compact = lowered.replace(" ", "")
    if len(compact) >= 2:
        rank = _RANK_WORDS.get(compact[:-1])
        suit = _SUIT_WORDS.get(compact[-1])
        if rank and suit:
            return f"{rank}{suit}"
    return None


def _unwrap(data: dict[str, Any]) -> dict[str, Any]:
    if any(key in data for key in ("seats", "street", "board", "total_pot")):
        return data
    for key in _NESTED_KEYS:
        inner = data.get(key)
        if isinstance(inner, dict):
            return inner
    return data


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _unit(value: Any, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        words = {"high": 0.9, "medium": 0.6, "low": 0.3}
        if value.strip().lower() in words:
            return words[value.strip().lower()]
        try:
            return max(0.0, min(1.0, float(value)))
        except ValueError:
            return default
    return default


def _parts(value: Any, default_confidence: float) -> tuple[Any, float]:
    if isinstance(value, dict) and "value" in value:
        return value.get("value"), _unit(value.get("confidence"), default_confidence)
    return value, default_confidence


def _obs(value: Any, confidence: float) -> dict[str, Any]:
    return {"value": value, "confidence": confidence}


def _plain_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"not an integer: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip().replace(",", "").replace("_", "")
    if text.endswith(".0"):
        text = text[:-2]
    return int(text)


def _optional_int(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and value.strip().lower() in {"", "null", "none"}):
        return None
    return _plain_int(value)


def _int_obs(
    value: Any, default_confidence: float, *, fallback: int | None = None, coerce: Any = None
) -> dict[str, Any]:
    raw, confidence = _parts(value, default_confidence)
    convert = coerce or _plain_int
    try:
        number = convert(raw)
    except (TypeError, ValueError):
        if fallback is None:
            raise
        number = fallback
        confidence = min(confidence, 0.2)
    return _obs(number, confidence)


def _enum_obs(value: Any, mapping: dict[str, str], default_confidence: float) -> dict[str, Any]:
    raw, confidence = _parts(value, default_confidence)
    if not isinstance(raw, str):
        raise PerceptionError(f"expected text, got {raw!r}")
    key = raw.strip().lower()
    if key not in mapping:
        raise PerceptionError(f"unknown value {raw!r}")
    return _obs(mapping[key], confidence)


def _card_obs(value: Any, default_confidence: float) -> dict[str, Any]:
    raw, confidence = _parts(value, default_confidence)
    code = normalize_card(raw)
    if (
        raw not in (None, "")
        and code is None
        and str(raw).strip().lower()
        not in {
            "null",
            "none",
            "unknown",
            "?",
            "??",
            "back",
        }
    ):
        confidence = min(confidence, 0.2)
    return _obs(code, confidence)


def _bool_obs(
    value: Any, default_confidence: float, *, fallback: bool | None = None
) -> dict[str, Any]:
    raw, confidence = _parts(value, default_confidence)
    if isinstance(raw, bool):
        return _obs(raw, confidence)
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw in (0, 1):
        return _obs(bool(raw), confidence)
    if isinstance(raw, str):
        word = raw.strip().lower()
        if word in {"true", "yes", "y", "1"}:
            return _obs(True, confidence)
        if word in {"false", "no", "n", "0"}:
            return _obs(False, confidence)
    if fallback is None:
        raise PerceptionError(f"expected true or false, got {raw!r}")
    return _obs(fallback, min(confidence, 0.2))


def _actor(value: Any, default_confidence: float) -> dict[str, Any]:
    raw, confidence = _parts(value, default_confidence)
    try:
        seat = _optional_int(raw)
    except (TypeError, ValueError) as exc:
        raise PerceptionError(f"actor seat was not an integer: {raw!r}") from exc
    return _obs(seat, confidence)


def _optional_seat(value: Any) -> int | None:
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    if value is None or value == "":
        return None
    try:
        return _optional_int(value)
    except (TypeError, ValueError):
        return None


def _timers(value: Any, default_confidence: float) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    if "shot_clock_ms" in data:
        shot = _int_obs(data["shot_clock_ms"], default_confidence)
    else:
        shot = _obs(20_000, 0.2)
    return {
        "shot_clock_ms": shot,
        "remaining_ms": _optional_int_obs(data.get("remaining_ms"), default_confidence),
        "deadline_unix_ms": _optional_int_obs(data.get("deadline_unix_ms"), default_confidence),
    }


def _optional_int_obs(value: Any, default_confidence: float) -> dict[str, Any]:
    if value is None:
        return _obs(None, 0.2)
    raw, confidence = _parts(value, default_confidence)
    try:
        return _obs(_optional_int(raw), confidence)
    except (TypeError, ValueError):
        return _obs(None, 0.2)


def _pot(value: dict[str, Any], default_confidence: float) -> dict[str, Any]:
    seats = []
    for seat in _as_list(value.get("eligible_seats")):
        try:
            number = _plain_int(seat)
        except (TypeError, ValueError):
            continue
        seats.append(number)
    return {"amount": _int_obs(value.get("amount"), default_confidence), "eligible_seats": seats}


def _seat(value: dict[str, Any], default_confidence: float) -> dict[str, Any]:
    seat: dict[str, Any] = {}
    if "seat" in value:
        seat["seat"] = _plain_int(_parts(value["seat"], default_confidence)[0])
    if "name" in value:
        raw, confidence = _parts(value["name"], default_confidence)
        seat["name"] = _obs(_text(raw) or "Seat", confidence)
    if "position" in value:
        seat["position"] = _position(value["position"], default_confidence)
    if "stack" in value:
        seat["stack"] = _int_obs(value["stack"], default_confidence)
    if "bet" in value:
        seat["bet"] = _int_obs(value["bet"], default_confidence)
    if "hole_cards" in value:
        seat["hole_cards"] = [
            _card_obs(card, default_confidence) for card in _as_list(value["hole_cards"])
        ]
    else:
        seat["hole_cards"] = []
    if "status" in value:
        seat["status"] = _enum_obs(value["status"], _STATUSES, default_confidence)
    seat["is_button"] = (
        _bool_obs(value["is_button"], default_confidence)
        if "is_button" in value
        else _obs(False, 0.2)
    )
    seat["is_actor"] = (
        _bool_obs(value["is_actor"], default_confidence)
        if "is_actor" in value
        else _obs(False, 0.2)
    )
    seat["hole_cards_shown"] = (
        _bool_obs(value["hole_cards_shown"], default_confidence)
        if "hole_cards_shown" in value
        else _obs(False, 0.2)
    )
    seat["payoff"] = (
        _optional_int_obs(value["payoff"], default_confidence)
        if "payoff" in value
        else _obs(None, 0.2)
    )
    return seat


def _position(value: Any, default_confidence: float) -> dict[str, Any]:
    raw, confidence = _parts(value, default_confidence)
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in {"", "null", "none", "-"}):
        return _obs(None, confidence)
    if not isinstance(raw, str):
        raise PerceptionError(f"position was not text: {raw!r}")
    key = raw.strip().lower()
    if key not in _POSITIONS:
        raise PerceptionError(f"unknown position {raw!r}")
    return _obs(_POSITIONS[key], confidence)


def _legal(value: Any, default_confidence: float) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_kind, confidence = _parts(value.get("kind"), default_confidence)
    if isinstance(value.get("confidence"), int | float) and not isinstance(
        value.get("confidence"), bool
    ):
        confidence = _unit(value.get("confidence"), confidence)
    if not isinstance(raw_kind, str):
        return None
    kind = _KINDS.get(raw_kind.strip().lower())
    if kind is None:
        return None
    action: dict[str, Any] = {
        "kind": kind,
        "sizing": [],
        "is_all_in": bool(value.get("is_all_in", False)),
        "confidence": confidence,
    }
    for key in ("amount", "min_to", "max_to"):
        if key in value and value[key] is not None:
            action[key] = _int_obs(value[key], default_confidence)
        else:
            action[key] = None
    for option in _as_list(value.get("sizing")):
        if not isinstance(option, dict):
            continue
        label_raw = option.get("label")
        if isinstance(label_raw, dict):
            label_raw = label_raw.get("value")
        if not isinstance(label_raw, str):
            continue
        label = _SIZING.get(label_raw.strip().lower())
        if label is None or "to_amount" not in option:
            continue
        action["sizing"].append(
            {"label": label, "to_amount": _int_obs(option["to_amount"], default_confidence)}
        )
    return action
