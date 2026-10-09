from __future__ import annotations

import re
from pathlib import Path

from starlette.testclient import TestClient

from app.settings import Settings
from app.web import create_app


def make_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        base_dir=tmp_path,
        data_dir=data_dir,
        db_path=data_dir / "state.db",
        session_path=data_dir / "account",
        admin_user="admin",
        initial_password="testpass",
        session_secret="test-secret",
        https_only=False,
        host="127.0.0.1",
        port=8100,
    )


def extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "csrf token not found"
    return match.group(1)


def login(client: TestClient) -> None:
    page = client.get("/login")
    csrf = extract_csrf(page.text)
    response = client.post(
        "/login",
        data={"username": "admin", "password": "testpass", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_anonymous_redirects_to_login(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_login_and_create_rule(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        login(client)
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "总览" in dashboard.text
        csrf = extract_csrf(dashboard.text)
        response = client.post(
            "/rules/new",
            data={
                "csrf_token": csrf,
                "name": "价格",
                "pattern": "价格",
                "match_type": "contains",
                "reply": "价格是 10 元",
                "cooldown_seconds": "300",
                "per_user_cooldown_seconds": "3600",
                "enabled": "on",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        rules_page = client.get("/rules")
        assert "价格是 10 元" not in rules_page.text
        assert "价格" in rules_page.text


def test_healthz_is_public(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_change_admin_password(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        login(client)
        settings_page = client.get("/settings")
        csrf = extract_csrf(settings_page.text)
        response = client.post(
            "/settings/password",
            data={
                "csrf_token": csrf,
                "current_password": "testpass",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        client.post("/logout", data={"csrf_token": extract_csrf(client.get("/").text)})
        page = client.get("/login")
        csrf = extract_csrf(page.text)
        response = client.post(
            "/login",
            data={"username": "admin", "password": "newpass123", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
