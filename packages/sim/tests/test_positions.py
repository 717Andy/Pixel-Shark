from pixelshark_sim.positions import pokerkit_order, position_for, ring_from_button


def test_six_max_ring_and_pokerkit_order():
    ring = ring_from_button(6, button=0, active=set(range(6)))
    assert ring == [0, 1, 2, 3, 4, 5]
    assert pokerkit_order(ring) == [1, 2, 3, 4, 5, 0]
    assert [position_for(ring, seat) for seat in ring] == ["BTN", "SB", "BB", "UTG", "HJ", "CO"]


def test_heads_up_button_is_small_blind_in_pokerkit_order():
    ring = ring_from_button(2, button=1, active={0, 1})
    assert ring == [1, 0]
    # PokerKit player 0 is the big blind in heads-up, which is the seat after the button.
    assert pokerkit_order(ring) == [0, 1]
    assert position_for(ring, 1) == "BTN"
    assert position_for(ring, 0) == "BB"


def test_sitting_out_button_walks_clockwise():
    ring = ring_from_button(3, button=0, active={1, 2})
    assert ring[0] == 1
    assert position_for(ring, 1) == "BTN"
    assert position_for(ring, 2) == "BB"


def test_full_ring_has_nine_names():
    ring = ring_from_button(9, button=3, active=set(range(9)))
    assert ring[0] == 3
    assert len({position_for(ring, seat) for seat in ring}) == 9
