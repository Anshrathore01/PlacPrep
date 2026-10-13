from scripts.remediate_mcq_content import (
    _classification,
    _content_blockers,
    normalize_answer_key,
)


def test_answer_key_normalization_maps_only_to_one_existing_label():
    options = [
        {"option_key": "A"},
        {"option_key": "B"},
        {"option_key": "C"},
        {"option_key": "D"},
    ]

    assert normalize_answer_key(" option a ", options) == "A"


def test_answer_key_normalization_matches_actual_lowercase_option_key():
    options = [
        {"option_key": "a"},
        {"option_key": "b"},
        {"option_key": "c"},
        {"option_key": "d"},
    ]

    assert normalize_answer_key("A", options) == "a"


def test_answer_key_normalization_does_not_change_exact_key():
    options = [{"option_key": "A"}, {"option_key": "B"}]

    assert normalize_answer_key("A", options) is None


def test_answer_key_normalization_rejects_missing_invalid_or_ambiguous_labels():
    assert normalize_answer_key(None, [{"option_key": "A"}]) is None
    assert normalize_answer_key("F", [{"option_key": "A"}]) is None
    assert (
        normalize_answer_key(
            "A",
            [{"option_key": "A"}, {"option_key": "a"}],
        )
        is None
    )


def test_content_defects_remain_blocking_without_source_evidence():
    row = {
        "blocker_reason": [
            "Unsupported option count: 3; expected 4 or 5.",
            "Latest review decision is PENDING.",
        ],
        "eligible_after_repair": False,
    }

    assert _content_blockers(row) == [
        "Unsupported option count: 3; expected 4 or 5."
    ]
    assert _classification(row, safe_repair_applied=False) == "BLOCKED"


def test_review_only_question_requires_review_not_content_repair():
    row = {
        "blocker_reason": [
            "Latest review decision is PENDING.",
            "Question is REVIEW, not PUBLISHED; reviewer approval is pending.",
        ],
        "eligible_after_repair": False,
    }

    assert not _content_blockers(row)
    assert _classification(row, safe_repair_applied=False) == "NEEDS_REVIEW"


def test_archived_question_remains_blocked():
    row = {
        "status": "ARCHIVED",
        "blocker_reason": [
            "Latest review decision is PENDING.",
            "Question is ARCHIVED.",
        ],
        "eligible_after_repair": False,
    }

    assert _classification(row, safe_repair_applied=False) == "BLOCKED"


def test_successful_safe_repair_is_reported_separately_from_eligibility():
    row = {
        "blocker_reason": [
            "Latest review decision is PENDING.",
            "Question is REVIEW, not PUBLISHED; reviewer approval is pending.",
        ],
        "eligible_after_repair": False,
    }

    assert _classification(row, safe_repair_applied=True) == "SAFE_REPAIR"


def test_canonical_eligibility_is_the_only_valid_classification():
    row = {"blocker_reason": [], "eligible_after_repair": True}

    assert _classification(row, safe_repair_applied=False) == "VALID"
