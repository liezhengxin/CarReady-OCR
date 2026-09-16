"""Disclosure endpoints.

The synthetic-data and placeholder-rubric notices are required by §9 and §7.4.
Serving them from the API rather than from a client constant means a synthetic
deployment cannot be made to look like a production one by editing client code.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.enums import ROLE_CAPABILITIES, Capability, Role


def test_healthz_does_not_require_auth(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_system_meta_declares_synthetic_mode(client: TestClient) -> None:
    body = client.get("/api/meta/system").json()
    assert body["synthetic_data_mode"] is True


def test_synthetic_banner_is_critical_and_not_dismissible(client: TestClient) -> None:
    """The banner exists precisely for the person who dismissed it an hour ago
    and is about to quote a number from this screen."""
    banners = {b["id"]: b for b in client.get("/api/meta/system").json()["banners"]}
    assert "synthetic_data" in banners
    assert banners["synthetic_data"]["severity"] == "critical"
    assert banners["synthetic_data"]["dismissible"] is False


def test_banner_copy_is_bahasa_indonesia(client: TestClient) -> None:
    banner = next(
        b for b in client.get("/api/meta/system").json()["banners"] if b["id"] == "synthetic_data"
    )
    assert "SINTETIS" in banner["title_id"]
    assert "tidak boleh digunakan" in banner["body_id"].lower()


def test_placeholder_rubric_is_disclosed(client: TestClient) -> None:
    body = client.get("/api/meta/system").json()
    assert body["grading_rubric_placeholder"] is True
    assert any(b["id"] == "placeholder_grading_rubric" for b in body["banners"])


def test_config_versions_are_reported(client: TestClient) -> None:
    """Surfaced so a support question about a past grade can be answered
    against the rubric version that produced it."""
    versions = client.get("/api/meta/system").json()["config_versions"]
    for name in ("grading", "pricing", "crosschecks", "capture", "catalog", "pdp", "providers"):
        assert versions.get(name)


def test_capability_map_matches_the_enum(client: TestClient) -> None:
    body = client.get("/api/meta/capabilities").json()
    assert set(body) == {r.value for r in Role}
    for role, caps in ROLE_CAPABILITIES.items():
        assert set(body[role.value]) == {c.value for c in caps}


def test_capability_map_confirms_inspectors_see_no_prices(client: TestClient) -> None:
    body = client.get("/api/meta/capabilities").json()
    assert Capability.UNIT_READ_PRICE.value not in body[Role.INSPECTOR.value]


def test_enum_endpoint_serves_the_damage_taxonomy(client: TestClient) -> None:
    """Client dropdowns are served from the same module the database CHECK
    constraints are built from, so the two cannot drift."""
    body = client.get("/api/meta/enums").json()
    assert "celah_panel" in body["damage_type"]
    assert "TAMPERED_SUSPECTED" in body["plate_condition"]
    assert len(body["panel"]) == 30
    assert len([c for c in body["capture_type"] if c.startswith("EXT_")]) == 9


def test_unknown_route_is_a_clean_404(client: TestClient) -> None:
    assert client.get("/api/does-not-exist").status_code == 404
