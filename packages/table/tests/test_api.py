from fastapi.testclient import TestClient

from pixelshark_table.app import create_app
from pixelshark_table.settings import Settings


def _client(**kwargs) -> TestClient:
    defaults = dict(
        autoplay=False,
        create_default=True,
        hero_seat=None,
        seed=1,
        seats=6,
        shot_clock_ms=20_000,
    )
    defaults.update(kwargs)
    app = create_app(Settings(**defaults))
    return TestClient(app)


def test_health_schema_and_homepage():
    with _client() as client:
        assert client.get("/health").json() == {"status": "ok"}
        schema = client.get("/api/schema").json()
        assert schema["$id"] == "urn:pixelshark:game-state:1.0.0"
        page = client.get("/")
        assert page.status_code == 200
        assert "Pixel Shark" in page.text
        assert "midnight" in page.text
        assert "linen" in page.text
        css = client.get("/static/styles.css")
        assert css.status_code == 200
        assert 'data-skin="broadcast"' in css.text or "broadcast" in css.text
        assert 'data-skin="linen"' in css.text
        session = client.get("/api/session").json()
        assert session["table_id"] == "home"
        state = session["state"]
        assert state["schema_version"] == "1.0.0"
        assert state["variant"] == "NLHE"
        assert len(state["seats"]) == 6


def test_action_fold_and_reject_the_wrong_seat():
    with _client(create_default=False) as client:
        created = client.post(
            "/api/tables",
            json={
                "seats": 2,
                "hero_seat": 0,
                "button_seat": 0,
                "seed": 4,
                "autoplay": False,
                "bot_seats": [1],
            },
        )
        assert created.status_code == 201
        table_id = created.json()["table_id"]
        state = created.json()["state"]
        assert state["actor_seat"]["value"] == 0
        rejected = client.post(
            f"/api/tables/{table_id}/actions",
            json={"seat": 1, "kind": "fold"},
        )
        assert rejected.status_code == 409
        folded = client.post(
            f"/api/tables/{table_id}/actions",
            json={"seat": 0, "kind": "fold"},
        )
        assert folded.status_code == 200
        assert folded.json()["hand_phase"]["value"] == "complete"
        assert sum(seat["stack"]["value"] for seat in folded.json()["seats"]) == 20_000


def test_step_plays_a_bot_and_websocket_receives_state():
    with _client(create_default=False) as client:
        # Heads-up with the button on seat 0: that seat posts the small blind and acts first.
        created = client.post(
            "/api/tables",
            json={"seats": 2, "hero_seat": 1, "button_seat": 0, "seed": 8, "bot_seats": [0]},
        )
        table_id = created.json()["table_id"]
        assert created.json()["state"]["actor_seat"]["value"] == 0
        with client.websocket_connect(f"/api/tables/{table_id}/ws") as socket:
            initial = socket.receive_json()
            assert initial["hand_id"] == created.json()["state"]["hand_id"]
            stepped = client.post(f"/api/tables/{table_id}/step")
            assert stepped.status_code == 200
            update = socket.receive_json()
            assert update["hand_number"]["value"] == initial["hand_number"]["value"]
            assert update["last_action"]


def test_missing_table_is_404():
    with _client() as client:
        assert client.get("/api/tables/missing").status_code == 404
