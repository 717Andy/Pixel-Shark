from pixelshark_executor import locate
from pixelshark_schema import Decision


def test_locate_centers_the_matching_raise_button():
    boxes = [
        {
            "label": "button",
            "x": 10,
            "y": 20,
            "width": 40,
            "height": 16,
            "attrs": {"kind": "dealer", "action": "dealer"},
        },
        {
            "label": "button",
            "x": 100,
            "y": 200,
            "width": 80,
            "height": 30,
            "attrs": {"kind": "action", "action": "raise", "to": "300"},
        },
        {
            "label": "button",
            "x": 200,
            "y": 200,
            "width": 80,
            "height": 30,
            "attrs": {"kind": "action", "action": "raise", "to": "600"},
        },
    ]
    click = locate(Decision(kind="raise", to_amount=600), boxes)
    assert click is not None
    assert (click.x, click.y) == (240, 215)


def test_locate_returns_none_when_the_button_is_missing():
    assert locate(Decision(kind="fold"), []) is None
