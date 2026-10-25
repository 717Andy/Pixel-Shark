from pixelshark_datagen.generate import HOLDOUT_SKIN, plans_for


def test_linen_is_only_added_when_asked():
    regular = plans_for(count=4, include_holdout=False)
    assert [plan["skin"] for plan in regular] == ["felt", "midnight", "broadcast", "midnight"]
    assert HOLDOUT_SKIN not in {plan["skin"] for plan in regular}
    with_holdout = plans_for(count=4, include_holdout=True)
    assert [plan["skin"] for plan in with_holdout] == [
        "felt",
        "midnight",
        "broadcast",
        "midnight",
        "linen",
    ]
    assert with_holdout[-1]["hero"] == 0
    assert with_holdout[-1]["wait_hero"] is True
