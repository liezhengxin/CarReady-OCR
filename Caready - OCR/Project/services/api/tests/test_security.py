"""Password hashing, tokens, and the capability model."""

from __future__ import annotations

import uuid

import pytest

from app.crypto import decrypt_text, encrypt_text
from app.enums import ROLE_CAPABILITIES, Capability, Role, UnitStatus, UNIT_TRANSITIONS
from app.security import (
    TokenError,
    can_read_prices,
    capabilities_for,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    has_capability,
    verify_password,
)


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def test_password_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_hash_is_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_password_hash_is_argon2id() -> None:
    assert hash_password("x").startswith("$argon2id$")


def test_verify_tolerates_a_corrupt_hash() -> None:
    """A malformed stored hash must fail the login, not raise a 500."""
    assert verify_password("anything", "not-a-hash") is False


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id, email="a@b.local", role=Role.APPRAISER, token_version=3, branch_code="JKT-01"
    )
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "appraiser"
    assert payload["tv"] == 3
    assert payload["typ"] == "access"


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(user_id=uuid.uuid4(), email="a@b.local", role=Role.INSPECTOR, token_version=1)
    head, payload, _ = token.split(".")
    with pytest.raises(TokenError):
        decode_access_token(f"{head}.{payload}.deadbeef")


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token("not-a-jwt")


def test_refresh_token_is_stored_only_as_a_hash() -> None:
    plaintext, stored = generate_refresh_token()
    assert plaintext != stored
    assert len(stored) == 64
    assert hash_refresh_token(plaintext) == stored


def test_refresh_tokens_are_unique() -> None:
    assert generate_refresh_token()[0] != generate_refresh_token()[0]


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


def test_inspectors_cannot_read_prices() -> None:
    """A business control, not a UI preference: an inspector who can see the
    price a unit is heading toward has an incentive to shade damage reporting
    toward it. Enforced server-side (§3)."""
    assert not can_read_prices(Role.INSPECTOR)
    assert not has_capability(Role.INSPECTOR, Capability.UNIT_READ_PRICE)


def test_appraisers_and_approvers_can_read_prices() -> None:
    assert can_read_prices(Role.APPRAISER)
    assert can_read_prices(Role.APPROVER)


def test_only_approvers_may_approve() -> None:
    """Separation of duties: the person who can change a grade must not be the
    same person who signs off the resulting price."""
    approving = {r for r in Role if has_capability(r, Capability.UNIT_APPROVE)}
    assert approving == {Role.APPROVER}


def test_appraisers_cannot_approve() -> None:
    assert not has_capability(Role.APPRAISER, Capability.UNIT_APPROVE)


def test_inspectors_cannot_override_grades() -> None:
    assert not has_capability(Role.INSPECTOR, Capability.UNIT_OVERRIDE_GRADE)
    assert not has_capability(Role.INSPECTOR, Capability.UNIT_OVERRIDE_DAMAGE)


def test_approver_is_a_superset_of_appraiser() -> None:
    assert capabilities_for(Role.APPRAISER) <= capabilities_for(Role.APPROVER)


def test_admin_cannot_approve_prices() -> None:
    """Admin is an operational role, not a commercial one. Model deployment and
    price approval are deliberately separated."""
    assert not has_capability(Role.ADMIN, Capability.UNIT_APPROVE)


def test_only_admin_may_deploy_models_or_change_config() -> None:
    for capability in (Capability.MODEL_DEPLOY, Capability.CONFIG_WRITE, Capability.USER_MANAGE):
        holders = {r for r in Role if has_capability(r, capability)}
        assert holders == {Role.ADMIN}, f"{capability.value} should be admin-only, held by {holders}"


def test_every_role_has_an_explicit_capability_set() -> None:
    """A role missing from the map silently gets no capabilities, which fails
    closed but confusingly. Make it explicit."""
    assert set(ROLE_CAPABILITIES) == set(Role)


def test_inspectors_cannot_unmask_pii() -> None:
    assert not has_capability(Role.INSPECTOR, Capability.PII_UNMASK)


# --------------------------------------------------------------------------
# State machine vocabulary
# --------------------------------------------------------------------------


def test_approved_is_terminal() -> None:
    assert UNIT_TRANSITIONS[UnitStatus.APPROVED] == frozenset()


def test_every_status_has_a_declared_transition_set() -> None:
    assert set(UNIT_TRANSITIONS) == set(UnitStatus)


def test_approval_is_only_reachable_from_pending_approval() -> None:
    """No AI-generated price is ever published without passing through human
    review (§8.6)."""
    sources = {s for s, targets in UNIT_TRANSITIONS.items() if UnitStatus.APPROVED in targets}
    assert sources == {UnitStatus.PENDING_APPROVAL}


def test_rejection_is_recoverable() -> None:
    """A rejected unit can be reworked, otherwise a single bad photo scraps it."""
    assert UnitStatus.DRAFT in UNIT_TRANSITIONS[UnitStatus.REJECTED]


# --------------------------------------------------------------------------
# PII encryption
# --------------------------------------------------------------------------


def test_pii_encryption_round_trip() -> None:
    plaintext = "Budi Santoso"
    ciphertext = encrypt_text(plaintext)
    assert ciphertext != plaintext
    assert decrypt_text(ciphertext) == plaintext


def test_ciphertext_is_non_deterministic() -> None:
    """Deterministic ciphertext would leak equality: an observer could tell two
    units share an owner without decrypting anything."""
    assert encrypt_text("Budi Santoso") != encrypt_text("Budi Santoso")


def test_undecryptable_value_returns_a_marker_rather_than_raising() -> None:
    """Raising would make an entire unit unreadable - including its non-PII
    fields - after a botched key rotation."""
    assert "tidak dapat didekripsi" in decrypt_text("gAAAAABm-not-a-valid-token")


def test_unicode_pii_survives_the_round_trip() -> None:
    value = "Jl. Cendrawasih No. 12, Yogyakarta — RT 03/RW 04"
    assert decrypt_text(encrypt_text(value)) == value
