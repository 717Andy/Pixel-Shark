from pixelshark_perception.backends import MockBackend
from pixelshark_perception.reader import VlmReader
from pixelshark_perception.watch import format_turn, iter_our_turns
from pixelshark_sim import Table


class _Screen:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames
        self.captures = 0

    def capture(self) -> bytes:
        image = self.frames[self.captures]
        self.captures += 1
        return image


def test_watch_prints_only_when_it_is_our_turn_and_never_acts():
    ours = Table(seats=2, seed=1, autoplay=False, hero_seat=0).snapshot()
    assert ours.actor_seat.value == 0
    waiting = Table(seats=6, seed=1, autoplay=False).snapshot()
    assert waiting.actor_seat.value != 0
    later = ours.model_copy(deep=True)
    later.hand_id = ours.hand_id + "-next"
    screen = _Screen([b"a", b"b", b"c", b"d"])
    reader = VlmReader(
        MockBackend(
            [
                waiting.model_dump_json(),
                ours.model_dump_json(),
                ours.model_dump_json(),
                later.model_dump_json(),
            ]
        )
    )
    results = list(
        iter_our_turns(
            screen, reader, hero_seat=0, frames=4, interval_s=0, sleep=lambda _seconds: None
        )
    )
    assert [result.state.hand_id for result in results] == [ours.hand_id, later.hand_id]
    text = format_turn(results[0])
    assert "our turn" in text
    assert "no action taken" in text
    assert "Fold" not in text
    assert screen.captures == 4


def test_a_bad_read_does_not_stop_the_loop():
    ours = Table(seats=2, seed=1, autoplay=False, hero_seat=0).snapshot()
    errors: list[str] = []
    screen = _Screen([b"a", b"b"])
    reader = VlmReader(MockBackend(["nope", ours.model_dump_json()]), attempts=1)
    results = list(
        iter_our_turns(
            screen,
            reader,
            hero_seat=0,
            frames=2,
            interval_s=0,
            on_error=lambda exc: errors.append(str(exc)),
        )
    )
    assert len(errors) == 1
    assert "schema-valid" in errors[0]
    assert len(results) == 1
