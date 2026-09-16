"""Business config validation.

These tests are the guard against the most dangerous class of failure in a
config-driven system: a YAML file and the code that reads it drifting apart
silently. A grading rubric referring to a panel the enum does not have would
not raise - it would quietly score zero and understate damage.
"""

from __future__ import annotations

import pytest

from app.config import CONFIG_DIR, config_version, grading_is_placeholder, load_config
from app.enums import (
    DamageType,
    NonVisualCheckItem,
    Panel,
    PlateCondition,
    TaxStatus,
)

CONFIG_NAMES = ("grading", "pricing", "crosschecks", "capture", "catalog", "pdp", "providers", "vin_wmi",
                "deduction_coldstart")


@pytest.mark.parametrize("name", CONFIG_NAMES)
def test_config_parses_and_is_versioned(name: str) -> None:
    data = load_config(name)
    assert isinstance(data, dict)
    assert config_version(name), f"{name}.yaml must declare a non-empty version"


def test_every_config_file_on_disk_is_covered_by_these_tests() -> None:
    """A new config file must be added to CONFIG_NAMES.

    Otherwise it ships unvalidated, which defeats the point of having these
    tests at all.
    """
    on_disk = {p.stem for p in CONFIG_DIR.glob("*.yaml")}
    assert on_disk == set(CONFIG_NAMES), (
        f"config/ and CONFIG_NAMES disagree. Only in config/: {on_disk - set(CONFIG_NAMES)}. "
        f"Only in CONFIG_NAMES: {set(CONFIG_NAMES) - on_disk}"
    )


# --------------------------------------------------------------------------
# grading.yaml
# --------------------------------------------------------------------------


def test_grading_base_points_cover_every_damage_type() -> None:
    base_points = load_config("grading")["base_points"]
    assert set(base_points) == set(DamageType.values())


def test_grading_base_points_define_all_three_severities() -> None:
    for damage_type, points in load_config("grading")["base_points"].items():
        assert set(points) == {1, 2, 3}, f"{damage_type} must define severity 1, 2 and 3"


def test_grading_base_points_increase_with_severity() -> None:
    for damage_type, points in load_config("grading")["base_points"].items():
        assert points[1] < points[2] < points[3], f"{damage_type} points must increase with severity"


def test_grading_panel_weights_cover_every_panel() -> None:
    weights = load_config("grading")["panel_weights"]
    assert set(weights) == set(Panel.values())


def test_celah_panel_outweighs_an_equivalent_scratch() -> None:
    """Panel gap is the strongest exterior-visible proxy for prior collision
    repair. A 10cm scratch is a cosmetic cost; a 10mm panel gap is evidence of
    structural repair history. The rubric must reflect that at every severity
    (§7.2) - this is a business rule, not a tuning preference.
    """
    base_points = load_config("grading")["base_points"]
    for severity in (1, 2, 3):
        assert base_points["celah_panel"][severity] > base_points["baret"][severity]


def test_grade_bands_are_ordered_and_terminated() -> None:
    bands = load_config("grading")["grade_bands"]
    finite = [b["max_score"] for b in bands if b["max_score"] is not None]
    assert finite == sorted(finite), "grade bands must be ordered best to worst"
    assert bands[-1]["max_score"] is None, "the last band must be an open-ended catch-all"
    assert all(b["max_score"] is not None for b in bands[:-1]), "only the last band may be open-ended"


def test_downgrade_rules_reference_known_labels_and_vocabulary() -> None:
    config = load_config("grading")
    labels = {b["label"] for b in config["grade_bands"]}
    for rule in config["downgrade_rules"]:
        assert rule["cap_at"] in labels, f"rule {rule['id']} caps at an unknown grade"
        clause = rule["when"].get("any_detection") or rule["when"].get("detection_count") or {}
        if "damage_type" in clause:
            assert clause["damage_type"] in DamageType.values()
        for panel in clause.get("panels", []):
            assert panel in Panel.values(), f"rule {rule['id']} references unknown panel {panel}"


def test_downgrade_rule_ids_are_unique() -> None:
    ids = [r["id"] for r in load_config("grading")["downgrade_rules"]]
    assert len(ids) == len(set(ids))


def test_grading_rubric_is_flagged_as_placeholder() -> None:
    """Until Caready confirms their scale, the rubric must declare itself a
    placeholder - that flag drives the UI warning and the pricing-confidence
    degradation. See docs/OPEN_ITEMS.md #1.

    When this test fails because someone set `rubric_status: ACTIVE`, that is
    the signal to close OPEN_ITEMS #1 and update this test - not to delete it.
    """
    assert load_config("grading")["rubric_status"] == "PLACEHOLDER"
    assert grading_is_placeholder() is True


# --------------------------------------------------------------------------
# deduction_coldstart.yaml
# --------------------------------------------------------------------------


def test_coldstart_deduction_covers_every_grade_band() -> None:
    labels = {b["label"] for b in load_config("grading")["grade_bands"]}
    assert set(load_config("deduction_coldstart")["grade_deduction_pct"]) == labels


def test_coldstart_deduction_increases_as_grade_worsens() -> None:
    config = load_config("deduction_coldstart")
    bands = [b["label"] for b in load_config("grading")["grade_bands"]]
    values = [config["grade_deduction_pct"][label] for label in bands]
    assert values == sorted(values), "a worse grade must not deduct less"


def test_coldstart_tax_deduction_covers_every_tax_status() -> None:
    assert set(load_config("deduction_coldstart")["tax_deduction_idr"]) == set(TaxStatus.values())


def test_coldstart_non_visual_deduction_covers_every_checklist_item() -> None:
    assert set(load_config("deduction_coldstart")["non_visual_deduction_pct"]) == set(
        NonVisualCheckItem.values()
    )


def test_flood_is_the_heaviest_non_visual_deduction() -> None:
    """Flood damage is invisible to exterior grading and is the single most
    value-destroying condition a unit can have. If some other item outranks it,
    the table has been mis-edited."""
    deductions = load_config("deduction_coldstart")["non_visual_deduction_pct"]
    assert deductions["flood_indication"] == max(deductions.values())


# --------------------------------------------------------------------------
# crosschecks.yaml
# --------------------------------------------------------------------------


def test_iso3779_ambiguous_characters_are_normalised() -> None:
    """ISO 3779 excludes I, O and Q because they are confusable with 1 and 0.
    OCR makes the same confusion, so both sides of every comparison must be
    normalised (§5.4)."""
    mapping = load_config("crosschecks")["normalisation"]["character_map"]
    assert mapping["O"] == "0"
    assert mapping["I"] == "1"
    assert mapping["Q"] == "0"


def test_normalisation_is_recorded() -> None:
    """A match that only holds after normalisation is weaker evidence than an
    exact one and must stay distinguishable in the audit trail."""
    assert load_config("crosschecks")["normalisation"]["record_normalisation_applied"] is True


def test_aggressive_normalisation_is_off_by_default() -> None:
    """S/5, B/8 and Z/2 substitutions materially raise the false-match rate on
    the fraud checks."""
    assert load_config("crosschecks")["normalisation"]["aggressive_map"] is False


def test_identity_mismatches_block() -> None:
    config = load_config("crosschecks")
    assert config["vin_match"]["severity"]["MISMATCH"] == "BLOCKER"
    assert config["engine_no_match"]["severity"]["MISMATCH"] == "BLOCKER"


def test_tampered_plate_blocks() -> None:
    """TAMPERED_SUSPECTED is a fraud signal, not a cosmetic one (§5.5)."""
    severities = load_config("crosschecks")["plate_condition"]["severity"]
    assert severities["TAMPERED_SUSPECTED"] == "BLOCKER"


def test_plate_condition_severity_covers_every_classification() -> None:
    assert set(load_config("crosschecks")["plate_condition"]["severity"]) == set(PlateCondition.values())


def test_missing_comparison_side_does_not_pass() -> None:
    """An unreadable VIN plate is not evidence that the VIN matches."""
    config = load_config("crosschecks")
    assert config["vin_match"]["on_missing_side"] != "PASS"
    assert config["engine_no_match"]["on_missing_side"] != "PASS"


def test_odometer_bounds_match_the_brief() -> None:
    config = load_config("crosschecks")["odometer_sanity"]
    assert config["min_km_per_year"] == 2000
    assert config["max_km_per_year"] == 40000


def test_odometer_rollback_is_treated_more_seriously_than_high_mileage() -> None:
    """A low reading on an old unit is a rollback signal. A high reading is a
    valuation input, not a fraud flag."""
    config = load_config("crosschecks")["odometer_sanity"]
    ranking = {"INFO": 0, "WARNING": 1, "BLOCKER": 2}
    assert ranking[config["severity"]["below_min"]] > ranking[config["severity"]["above_max"]]


def test_identity_fields_have_the_strictest_confidence_thresholds() -> None:
    thresholds = load_config("crosschecks")["field_confidence"]["thresholds"]
    assert thresholds["nomor_rangka"] >= 0.90
    assert thresholds["nomor_mesin"] >= 0.90
    assert thresholds["nomor_rangka"] > thresholds["warna"]


def test_vin_decoding_can_never_overwrite_the_stnk() -> None:
    """The STNK is authoritative for brand/type/model/year. There is no public
    Indonesian VIN decoding database, and many domestic CKD units do not follow
    ISO 3779 for the model-year character (§5.3)."""
    config = load_config("crosschecks")["vin_decode"]
    assert config["never_overwrite_stnk"] is True
    assert config["decode_model_year"] is False


# --------------------------------------------------------------------------
# pricing.yaml
# --------------------------------------------------------------------------


def test_base_price_uses_a_lower_quantile_than_amp() -> None:
    """Setting a floor is a risk decision, not a point forecast (§8.4)."""
    quantiles = load_config("pricing")["quantiles"]
    assert quantiles["base_price_quantile"] < quantiles["amp_quantile"]


def test_every_used_quantile_is_actually_trained() -> None:
    quantiles = load_config("pricing")["quantiles"]
    trained = set(quantiles["train"])
    for key in ("amp_quantile", "base_price_quantile", "band_lower_quantile", "band_upper_quantile"):
        assert quantiles[key] in trained, f"{key} is not in the trained quantile set"


def test_unsold_units_are_included_in_training() -> None:
    """Training only on sold units biases the model upward and inflates floor
    prices - the exact failure this system exists to prevent (§8.3)."""
    assert load_config("pricing")["censoring"]["include_unsold"] is True


def test_no_bid_rows_are_weighted_below_below_reserve_rows() -> None:
    """A lot that attracted bids but missed reserve locates true value far more
    precisely than one nobody bid on."""
    censoring = load_config("pricing")["censoring"]
    assert censoring["no_bid_sample_weight"] < censoring["censored_sample_weight"]


def test_censored_rows_are_weighted_below_sold_rows() -> None:
    assert 0 < load_config("pricing")["censoring"]["censored_sample_weight"] < 1.0


def test_training_split_is_temporal() -> None:
    """A random split leaks future market conditions into training and flatters
    holdout metrics."""
    assert load_config("pricing")["training"]["split"] == "temporal"


def test_baselines_are_enabled() -> None:
    """OLS/ridge are explainability aids and the honesty check on whether
    LightGBM earns its complexity (§8.2)."""
    assert load_config("pricing")["baselines"]["enabled"] is True


def test_unresolved_variant_degrades_confidence_most() -> None:
    """An unresolved variant produces systematic, directional error - worse
    than thin comparables, which produce noise (§6.1)."""
    degradations = {d["condition"]: d["levels"] for d in load_config("pricing")["confidence"]["degrade_when"]}
    assert degradations["variant_unresolved"] >= degradations["data_tier_thin"]


def test_comparables_include_unsold() -> None:
    """Showing only sold comparables flatters the price."""
    assert load_config("pricing")["explanation"]["comparables"]["include_unsold"] is True


def test_guard_rails_bound_price_to_new_car_value() -> None:
    rails = load_config("pricing")["guard_rails"]
    assert rails["max_share_of_otr"] <= 1.0, "a used unit cannot be worth more than new"
    assert rails["min_share_of_otr"] > 0
    assert rails["enforce_quantile_monotonicity"] is True


def test_data_sufficiency_tiers_are_ordered_by_comparable_count() -> None:
    tiers = load_config("pricing")["data_sufficiency"]["tiers"]
    counts = [t["min_comparables"] for t in tiers]
    assert counts == sorted(counts, reverse=True)


# --------------------------------------------------------------------------
# capture.yaml
# --------------------------------------------------------------------------


def test_gallery_upload_is_disabled() -> None:
    """Camera capture only (§4.2). Gallery upload would let an inspector submit
    a photo taken elsewhere, at another time, of another car."""
    rules = load_config("capture")["rules"]
    assert rules["camera_only"] is True
    assert rules["allow_gallery_upload"] is False
    assert rules["allow_gallery_upload_for_closeups"] is False


def test_originals_are_never_overwritten() -> None:
    rules = load_config("capture")["rules"]
    assert rules["store_original"] is True
    assert rules["preserve_original_exif"] is True


def test_all_nine_exterior_angles_are_required_for_grading() -> None:
    from app.enums import EXTERIOR_CAPTURES

    required = load_config("capture")["completeness"]["required_for_grading"]
    assert set(required) == {c.value for c in EXTERIOR_CAPTURES}
    assert len(required) == 9


def test_unit_creation_requires_vin_and_stnk() -> None:
    """A unit is not created server-side until captures 1 and 2 have synced
    (§4.3)."""
    assert set(load_config("capture")["completeness"]["required_for_unit_creation"]) == {
        "INTAKE_VIN_PLATE",
        "INTAKE_STNK_FRONT",
    }


def test_overlays_exist_for_every_capture_type() -> None:
    from app.enums import CaptureType

    assert set(load_config("capture")["overlays"]) == set(CaptureType.values())


def test_document_captures_demand_sharper_focus_than_car_shots() -> None:
    blur = load_config("capture")["quality_gate"]["blur"]
    for capture in ("INTAKE_VIN_PLATE", "INTAKE_ENGINE_NO"):
        assert blur["min_variance_by_capture"][capture] > blur["min_variance"]


def test_offline_idempotency_is_client_generated() -> None:
    """The dedupe key must come from the client, or a retried upload the client
    never saw a response to becomes a duplicate (§4.3)."""
    assert load_config("capture")["offline"]["idempotency_key_source"] == "client_uuid_v4"


# --------------------------------------------------------------------------
# catalog.yaml
# --------------------------------------------------------------------------


def test_catalog_thresholds_leave_a_human_review_band() -> None:
    """The gap between auto-accept and the suggestion floor is deliberate dead
    space where an appraiser decides, rather than the system guessing (§6.1)."""
    matching = load_config("catalog")["matching"]
    assert matching["auto_accept_score"] > matching["suggest_score"]


def test_transmission_ambiguity_blocks_auto_accept() -> None:
    """The STNK does not record transmission at all, so this is precisely the
    ambiguity that must reach a human."""
    assert load_config("catalog")["matching"]["block_auto_accept_on_transmission_ambiguity"] is True


def test_unresolved_variant_blocks_pricing_entirely() -> None:
    """Stricter than degrading confidence, and deliberately so: a price
    computed on a guessed variant looks authoritative and is directionally
    wrong."""
    unresolved = load_config("catalog")["unresolved"]
    assert unresolved["block_pricing"] is True
    assert unresolved["block_auto_progression"] is True


def test_conflicting_aliases_are_quarantined_not_voted_on() -> None:
    assert load_config("catalog")["learning"]["quarantine_on_conflict"] is True


# --------------------------------------------------------------------------
# pdp.yaml
# --------------------------------------------------------------------------


def test_nik_is_classified_as_specific_personal_data() -> None:
    """Art. 4(3) data pribadi spesifik - stricter handling than general PII."""
    fields = load_config("pdp")["fields"]
    assert fields["unit_stnk_data.nik"]["class"] == "specific"
    assert fields["unit_stnk_data.nik"]["masking"] == "full"


def test_specific_pii_requires_a_typed_justification_to_unmask() -> None:
    assert load_config("pdp")["classes"]["specific"]["unmask_requires_justification"] is True


def test_all_pii_classes_log_access() -> None:
    for name, spec in load_config("pdp")["classes"].items():
        assert spec["log_access"] is True, f"PII class {name} must log access"
        assert spec["mask_by_default"] is True


def test_raw_pii_is_not_sent_to_external_providers_by_default() -> None:
    third_party = load_config("pdp")["third_party"]
    assert third_party["allow_raw_pii_to_external_providers"] is False
    assert third_party["on_template_match_failure"] == "refuse_external_call"


def test_retention_purge_is_in_dry_run_until_legal_sign_off() -> None:
    """Retention periods are unconfirmed placeholders - see OPEN_ITEMS #7.
    Deleting personal data on a guessed schedule is its own compliance failure.
    """
    assert load_config("pdp")["retention"]["dry_run"] is True


def test_access_log_outlives_the_data_it_describes() -> None:
    """Answering "who looked at this person's data" after the data is gone is
    the point of an access log."""
    policies = {p["entity"]: p for p in load_config("pdp")["retention"]["policies"]}
    assert policies["pii_access_log"]["retain_days"] > policies["unit_stnk_data"]["retain_days"]


def test_photo_buckets_are_never_public() -> None:
    storage = load_config("pdp")["object_storage"]
    assert storage["bucket_public_access"] is False
    assert 0 < storage["signed_url_ttl_seconds"] <= 900


# --------------------------------------------------------------------------
# providers.yaml
# --------------------------------------------------------------------------


def test_ci_defaults_reach_no_external_service() -> None:
    config = load_config("providers")
    assert config["ocr"]["provider"] == "stub"
    assert config["vision"]["provider"] == "stub"
    assert config["price_ingestion"]["adapter"] == "csv"


def test_raw_provider_responses_are_persisted_for_audit() -> None:
    config = load_config("providers")
    assert config["ocr"]["persist_raw_response"] is True
    assert config["vision"]["persist_inference"] is True
    assert config["vision"]["record_prompt_hash"] is True


def test_vision_schema_violations_fail_rather_than_coerce() -> None:
    """A half-parsed detection set silently understates damage, which biases
    price upward."""
    assert load_config("providers")["vision"]["providers"]["vlm"]["on_schema_violation"] == (
        "retry_then_fail"
    )


def test_scraper_respects_robots_and_fails_loudly() -> None:
    """Silently returning stale data corrupts the residual-value anchor without
    anyone noticing (§6.2)."""
    web = load_config("providers")["price_ingestion"]["adapters"]["web"]
    assert web["respect_robots_txt"] is True
    assert web["on_zero_results"] == "alert_and_fail"
    assert web["on_selector_miss"] == "alert_and_fail"


def test_label_store_keeps_negatives() -> None:
    """Deletions are hard negatives and are as valuable as confirmations for
    Stage 2 training (§7.3)."""
    assert load_config("providers")["label_store"]["keep_negatives"] is True
