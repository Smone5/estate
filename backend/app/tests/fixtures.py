"""
Solver & State Transition Test Fixtures
=========================================
Realistic datasets for testing Fairpyx MNW solver termination,
deterministic tie-breaker resolution, status transitions, and
LangGraph validation loopbacks.

Import in pytest tests:
    from app.tests.fixtures import (
        VALID_ALLOCATIONS, TIED_ALLOCATIONS, DEADLOCKED_ALLOCATIONS,
        HEIR_STATUS_SCENARIOS, OCR_STAGED_ASSETS
    )
"""

# ── Heir test data ─────────────────────────────────────────────────────────

HEIR_ALICE = {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "username": "Alice",
    "legal_first_name": "Alice",
    "legal_last_name": "Melton",
    "status": "ACTIVE",
    "is_submitted": False,
    "submitted_at": None,
}

HEIR_BOB = {
    "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    "username": "Bob",
    "legal_first_name": "Bob",
    "legal_last_name": "Melton",
    "status": "ACTIVE",
    "is_submitted": False,
    "submitted_at": None,
}

HEIR_CHARLIE = {
    "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    "username": "Charlie",
    "legal_first_name": "Charlie",
    "legal_last_name": "Melton",
    "status": "ACTIVE",
    "is_submitted": False,
    "submitted_at": None,
}

# ── Asset test data ─────────────────────────────────────────────────────────

ASSET_CLOCK = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "Grandfather Clock",
    "category": "Furniture",
    "valuation_min": 2500.0,
    "valuation_max": 4500.0,
    "valuation_source": "Professional Appraisal",
    "sentiment_tag": "antique, family heirloom",
}

ASSET_PAINTING = {
    "id": "22222222-2222-2222-2222-222222222222",
    "title": "Landscape Oil Painting",
    "category": "Art",
    "valuation_min": 800.0,
    "valuation_max": 1500.0,
    "valuation_source": "Auction Estimate",
    "sentiment_tag": "original, signed",
}

ASSET_RING = {
    "id": "33333333-3333-3333-3333-333333333333",
    "title": "Diamond Ring",
    "category": "Jewelry",
    "valuation_min": 3000.0,
    "valuation_max": 6000.0,
    "valuation_source": "Jeweler Appraisal",
    "sentiment_tag": "engagement, vintage",
}

# ── Scenario 1: Valid allocations (sums to 1000 each) ───────────────────────

VALID_ALLOCATIONS = {
    "heirs": [HEIR_ALICE, HEIR_BOB, HEIR_CHARLIE],
    "assets": [ASSET_CLOCK, ASSET_PAINTING, ASSET_RING],
    "valuations": {
        # Alice: 500 clock, 300 painting, 200 ring = 1000
        HEIR_ALICE["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 500, "reasoning": "Always loved this clock."},
            {"asset_id": ASSET_PAINTING["id"], "points": 300, "reasoning": "Matches my study."},
            {"asset_id": ASSET_RING["id"], "points": 200, "reasoning": "Beautiful ring."},
        ],
        # Bob: 400 clock, 600 ring, 0 painting = 1000
        HEIR_BOB["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 400, "reasoning": "Dad's favorite."},
            {"asset_id": ASSET_PAINTING["id"], "points": 0, "reasoning": ""},
            {"asset_id": ASSET_RING["id"], "points": 600, "reasoning": "For my wife."},
        ],
        # Charlie: 100 clock, 700 painting, 200 ring = 1000
        HEIR_CHARLIE["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 100, "reasoning": "Small apartment."},
            {"asset_id": ASSET_PAINTING["id"], "points": 700, "reasoning": "Art collector."},
            {"asset_id": ASSET_RING["id"], "points": 200, "reasoning": "Nice ring."},
        ],
    },
    "expected_outcome": "solved",  # No ties, no starvation
}

# ── Scenario 2: Tied allocations (deterministic tie-breaker must resolve) ───

TIED_ALLOCATIONS = {
    "heirs": [HEIR_ALICE, HEIR_BOB],
    "assets": [ASSET_CLOCK, ASSET_PAINTING],
    "valuations": {
        # Alice: 1000 clock, 0 painting
        HEIR_ALICE["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 1000, "reasoning": "Must have the clock."},
            {"asset_id": ASSET_PAINTING["id"], "points": 0, "reasoning": ""},
        ],
        # Bob: 1000 clock, 0 painting — TIE with Alice
        HEIR_BOB["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 1000, "reasoning": "Heirloom I want."},
            {"asset_id": ASSET_PAINTING["id"], "points": 0, "reasoning": ""},
        ],
    },
    "expected_outcome": "tie_break",
    "tie_breaker_fields": ["submitted_at", "uuid"],
}

# ── Scenario 3: Deadlocked (mutually exclusive maximum priority) ────────────

DEADLOCKED_ALLOCATIONS = {
    "heirs": [HEIR_ALICE, HEIR_BOB],
    "assets": [ASSET_CLOCK],
    "valuations": {
        HEIR_ALICE["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 1000, "reasoning": ""},
        ],
        HEIR_BOB["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 1000, "reasoning": ""},
        ],
    },
    "expected_outcome": "deadlock",  # Single asset, both want it fully
}

# ── Scenario 4: Starvation bypass (more heirs than live assets) ─────────────

STARVATION_BYPASS_ALLOCATIONS = {
    "heirs": [HEIR_ALICE, HEIR_BOB, HEIR_CHARLIE],
    "assets": [ASSET_CLOCK],
    "valuations": {
        HEIR_ALICE["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 600, "reasoning": ""},
        ],
        HEIR_BOB["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 300, "reasoning": ""},
        ],
        HEIR_CHARLIE["id"]: [
            {"asset_id": ASSET_CLOCK["id"], "points": 100, "reasoning": ""},
        ],
    },
    "expected_outcome": "starvation_bypass",  # 3 heirs, 1 asset → bypass enforced
}

# ── Scenario 5: Heir statuses (full lifecycle) ──────────────────────────────

HEIR_STATUS_SCENARIOS = [
    {"status": "PENDING", "can_submit": False, "can_chat": False, "can_draft": False},
    {"status": "PROFILE_HOLD", "can_submit": False, "can_chat": False, "can_draft": False},
    {"status": "ACTIVE", "can_submit": True, "can_chat": True, "can_draft": True},
    {"status": "SUBMITTED", "can_submit": False, "can_chat": False, "can_draft": False},
    {"status": "ABSTAINED", "can_submit": False, "can_chat": False, "can_draft": False},
    {"status": "EXPIRED_NON_PARTICIPATING", "can_submit": False, "can_chat": False, "can_draft": False},
]

# ── Scenario 6: OCR staged assets (validation gate testing) ─────────────────

OCR_STAGED_ASSETS = [
    {
        "description": "Fully populated (should pass validation gate)",
        "asset": {
            "title": "Antique Desk",
            "description": "Late-Victorian mahogany desk with brass hardware.",
            "category": "Furniture",
            "valuation_min": 800.0,
            "valuation_max": 1500.0,
            "valuation_source": "Estate Sale Estimate",
            "sentiment_tag": "antique, mahogany, desk",
        },
        "expect_publish_success": True,
    },
    {
        "description": "Missing valuation_source (should fail validation gate)",
        "asset": {
            "title": "Vintage Vase",
            "description": "Hand-painted ceramic vase.",
            "category": "Other",
            "valuation_min": 50.0,
            "valuation_max": 200.0,
            "valuation_source": None,  # Missing required field per DB Spec §2.3
            "sentiment_tag": "ceramic, vintage",
        },
        "expect_publish_success": False,
    },
    {
        "description": "Missing title (should fail validation gate)",
        "asset": {
            "title": "",  # Empty title
            "description": "A beautiful landscape oil painting signed by the artist.",
            "category": "Art",
            "valuation_min": 500.0,
            "valuation_max": 1200.0,
            "valuation_source": "Gallery Appraisal",
            "sentiment_tag": "landscape, signed",
        },
        "expect_publish_success": False,
    },
]