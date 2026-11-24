"""바탕화면 배경 고른 값(ui-state 의 appearance) — 화면 상태와 같은 길로 계정에 붙어 기기 사이를 따라간다."""

APPEARANCE = {"v": 1, "wallpaper": "contours", "fit": "fill"}


def test_put_then_get(client, user):
    r = client.put("/api/me/ui-state/appearance", json=APPEARANCE, headers=user)
    assert r.status_code == 200 and r.json()["mode"] == "appearance"
    assert client.get("/api/me/ui-state", headers=user).json()["appearance"]["state"] == APPEARANCE


def test_every_choice_is_accepted(client, user):
    ids = ["default", "prism-schedule", "orbits", "contours", "drafting-grid", "sculpt-mono", "chronos-sky",
           "minimal-warm", "minimal-cool", "photo"]
    for wid in ids:
        for fit in ["fill", "fit", "stretch", "tile", "center"]:
            body = {"v": 1, "wallpaper": wid, "fit": fit}
            assert client.put("/api/me/ui-state/appearance", json=body, headers=user).status_code == 200, body


def test_bad_values_are_422(client, user):
    for body in (
        {**APPEARANCE, "wallpaper": "aurora"},
        {**APPEARANCE, "wallpaper": "../x.png"},
        {**APPEARANCE, "fit": "cover"},
        {**APPEARANCE, "extra": 1},
        {"v": 1, "wallpaper": "orbits"},
    ):
        assert client.put("/api/me/ui-state/appearance", json=body, headers=user).status_code == 422, body


def test_other_user_does_not_see_mine(client, user, admin):
    client.put("/api/me/ui-state/appearance", json=APPEARANCE, headers=user)
    assert "appearance" not in client.get("/api/me/ui-state", headers=admin).json()
