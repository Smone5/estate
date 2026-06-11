"""
Fairpyx MNW Solver & Tie-Breakers — T15.

Integrates the Fairpyx library to compute fair allocations for estate
asset division.  Implements deterministic tie-breaking based on
submission timestamps and UUID fallback, plus zero-utility starvation
bypass for edge cases where there are more active heirs than available
assets.

Exports consumed by downstream tasks:
  - solve_mnw(...) → returns full allocation result including
    mnw_product_value (float) consumed by T14 PDF builder and
    tie_breaker_events (list) consumed by T70 tie-breaker record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union

import fairpyx
from fairpyx import divide, Instance
from fairpyx.algorithms import iterated_maximum_matching


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SolverAsset:
    """Asset input record consumed by the MNW solver."""
    asset_id: str
    pre_allocated_to: str | None = None  # heir UUID if pre-allocated


@dataclass(frozen=True)
class SolverHeir:
    """Heir input record consumed by the MNW solver."""
    heir_id: str
    submitted_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class TieBreakerEvent:
    """Structured record of a single tie-breaker resolution — T70 data contract.

    Consumed by T14/T70 PDF builder for the Deterministic Tie-Breaker
    Resolution Record table per Legal Spec §3 Item 6.
    """
    asset_id: str
    tied_heir_ids: list[str]
    points: int
    winner_heir_id: str
    reason: str  # e.g. "earlier submitted_at", "UUID fallback", "no bids"
    event_description: str  # Human-readable string for the audit description


@dataclass(frozen=True)
class SolverResult:
    """Complete result of a solver run.

    Attributes:
        allocation:  Mapping from heir_id -> list[asset_id].
        mnw_product_value:  Scalar product of utilities (0.0 if no assets).
        tie_breaker_events:  Structured TieBreakerEvent records (T70 contract).
    """
    allocation: dict[str, list[str]] = field(default_factory=dict)
    mnw_product_value: float = 0.0
    tie_breaker_events: list[TieBreakerEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _to_unix_epoch(dt: Optional[Union[datetime, float, int]]) -> float:
    """Convert a datetime (or already-epoch float) to float Unix epoch.

    Returns 0.0 for None inputs so that missing timestamps sort last
    (earliest epoch = 0.0 wins tie-breaker).
    """
    if dt is None:
        return 0.0
    if isinstance(dt, (int, float)):
        return float(dt)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve_mnw(
    heir_ids: list[str],
    asset_ids: list[str],
    valuations: dict[str, dict[str, int]],  # heir_id -> asset_id -> points
    pre_allocated: dict[str, str] | None = None,  # asset_id -> heir_id
    submission_times: dict[str, datetime] | None = None,
    creation_times: dict[str, datetime] | None = None,
) -> SolverResult:
    """Run the Fairpyx solver with deterministic tie-breaking.

    Args:
        heir_ids:  Ordered list of active heir UUID strings.
        asset_ids:  Ordered list of LIVE (non-pre-allocated) asset UUIDs.
        valuations:  Nested dict heir_id -> asset_id -> int points.
        pre_allocated:  Mapping of asset_id -> heir_id that was locked
            during SETUP (these are excluded from the solver and directly
            added to the result allocation).
        submission_times:  heir_id -> datetime they submitted.
        creation_times:  heir_id -> datetime they were created.

    Returns:
        SolverResult with allocation, mnw_product_value, and tie_breaker_events.
    """
    pre_allocated = pre_allocated or {}
    submission_times = submission_times or {}
    creation_times = creation_times or {}
    tie_breaker_events: list[TieBreakerEvent] = []

    result_allocation: dict[str, list[str]] = {
        hid: [] for hid in heir_ids
    }

    # Start with pre-allocated assets
    for aid, hid in pre_allocated.items():
        if hid in result_allocation:
            result_allocation[hid].append(aid)

    # Filter to only LIVE assets (not pre-allocated)
    live_asset_ids = [aid for aid in asset_ids if aid not in pre_allocated]

    if not live_asset_ids or not heir_ids:
        return SolverResult(
            allocation=result_allocation,
            mnw_product_value=0.0,
            tie_breaker_events=tie_breaker_events,
        )

    # Build valuation matrix in fairpyx Instance format:
    #   item_id -> { agent_id -> float(value) }
    item_valuations: dict[str, dict[str, float]] = {}
    for aid in live_asset_ids:
        item_valuations[aid] = {}
        for hid in heir_ids:
            points = valuations.get(hid, {}).get(aid, 0)
            item_valuations[aid][hid] = float(points)

    num_heirs = len(heir_ids)
    num_assets = len(live_asset_ids)

    # Zero-utility starvation bypass: more heirs than live assets.
    # The spec mandates bypassing the zero-utility starvation check
    # when mathematically impossible to allocate to everyone.
    if num_heirs > num_assets:
        return _starvation_bypass(
            heir_ids=heir_ids,
            asset_ids=live_asset_ids,
            valuations=valuations,
            submission_times=submission_times,
            creation_times=creation_times,
            existing_allocation=result_allocation,
            tie_breaker_events=tie_breaker_events,
        )

    # Build fairpyx Instance and run iterative maximum matching
    instance = Instance(
        valuations=item_valuations,
        agent_capacities=None,
    )

    try:
        # fairpyx.divide returns a dict[item_id, list[agent_id]]
        raw_allocation: dict = divide(
            algorithm=iterated_maximum_matching,
            instance=instance,
        )
    except Exception:
        return _starvation_bypass(
            heir_ids=heir_ids,
            asset_ids=live_asset_ids,
            valuations=valuations,
            submission_times=submission_times,
            creation_times=creation_times,
            existing_allocation=result_allocation,
            tie_breaker_events=tie_breaker_events,
        )

    # Map fairpyx allocation (item → list[agent]) to our format
    # (agent → list[item])
    for aid, agent_list in raw_allocation.items():
        for hid in agent_list:
            if hid in result_allocation:
                if aid not in result_allocation[hid]:
                    result_allocation[hid].append(aid)

    # --- Tie-breaker resolution for any unallocated assets ---
    allocated_set = set()
    for items in result_allocation.values():
        allocated_set.update(items)

    unallocated = [aid for aid in live_asset_ids if aid not in allocated_set]
    if unallocated:
        _resolve_ties(
            unallocated_assets=unallocated,
            heir_ids=heir_ids,
            valuations=valuations,
            submission_times=submission_times,
            creation_times=creation_times,
            result_allocation=result_allocation,
            tie_breaker_events=tie_breaker_events,
        )

    mnw_product_value = _compute_mnw_product(
        heir_ids=heir_ids,
        asset_ids=live_asset_ids,
        valuations=valuations,
        allocation=result_allocation,
    )

    return SolverResult(
        allocation=result_allocation,
        mnw_product_value=mnw_product_value,
        tie_breaker_events=tie_breaker_events,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_ties(
    unallocated_assets: list[str],
    heir_ids: list[str],
    valuations: dict[str, dict[str, int]],
    submission_times: dict[str, datetime],
    creation_times: dict[str, datetime],
    result_allocation: dict[str, list[str]],
    tie_breaker_events: list[TieBreakerEvent],
) -> None:
    """Assign unallocated assets using deterministic tie-breaking.

    For each unallocated asset:
      1. Find the set of heirs who bid the maximum non-zero points.
      2. If exactly one, assign to that heir.
      3. If multiple, break tie: earlier submitted_at → earlier created_at → UUID.
    """
    for aid in unallocated_assets:
        bids: list[tuple[str, int]] = []
        for hid in heir_ids:
            pts = valuations.get(hid, {}).get(aid, 0)
            bids.append((hid, pts))

        max_pts = max((pts for _, pts in bids), default=0)
        if max_pts == 0:
            ordered = _tie_breaker_sort(heir_ids, submission_times, creation_times)
            winner = ordered[0]
            result_allocation[winner].append(aid)
            desc = (
                f"Asset {aid}: No bids — assigned to {winner} "
                f"(deterministic fallback ordering)"
            )
            tie_breaker_events.append(TieBreakerEvent(
                asset_id=aid,
                tied_heir_ids=list(heir_ids),
                points=0,
                winner_heir_id=winner,
                reason="no bids — deterministic fallback",
                event_description=desc,
            ))
            continue

        candidates = [hid for hid, pts in bids if pts == max_pts]

        if len(candidates) == 1:
            result_allocation[candidates[0]].append(aid)
            continue

        ordered = _tie_breaker_sort(candidates, submission_times, creation_times)
        winner = ordered[0]
        result_allocation[winner].append(aid)
        # Determine the actual tie-breaker reason
        winner_sub = _to_unix_epoch(submission_times.get(winner))
        loser_sub = _to_unix_epoch(submission_times.get(candidates[1]))
        if winner_sub < loser_sub:
            reason = "earlier submitted_at"
        elif _to_unix_epoch(creation_times.get(winner)) < _to_unix_epoch(creation_times.get(candidates[1])):
            reason = "earlier created_at"
        else:
            reason = "UUID fallback"
        desc = (
            f"Asset {aid}: Tied at {max_pts} points among "
            f"{', '.join(candidates)} → {winner} "
            f"({reason})"
        )
        tie_breaker_events.append(TieBreakerEvent(
            asset_id=aid,
            tied_heir_ids=candidates,
            points=max_pts,
            winner_heir_id=winner,
            reason=reason,
            event_description=desc,
        ))


def _tie_breaker_sort(
    heir_ids: list[str],
    submission_times: dict[str, datetime],
    creation_times: dict[str, datetime],
) -> list[str]:
    """Sort heir IDs by: earliest submitted_at → earliest created_at → UUID."""
    def sort_key(hid: str) -> tuple[float, float, str]:
        sub_epoch = _to_unix_epoch(submission_times.get(hid))
        cre_epoch = _to_unix_epoch(creation_times.get(hid))
        return (sub_epoch, cre_epoch, hid.lower())

    return sorted(heir_ids, key=sort_key)


def _starvation_bypass(
    heir_ids: list[str],
    asset_ids: list[str],
    valuations: dict[str, dict[str, int]],
    submission_times: dict[str, datetime],
    creation_times: dict[str, datetime],
    existing_allocation: dict[str, list[str]],
    tie_breaker_events: list[TieBreakerEvent],
) -> SolverResult:
    """Handle the case where there are more heirs than live assets.

    Assigns assets to the earliest-submitting heirs deterministically.
    """
    ordered_heirs = _tie_breaker_sort(heir_ids, submission_times, creation_times)

    for i, aid in enumerate(asset_ids):
        if i < len(ordered_heirs):
            winner = ordered_heirs[i]
            existing_allocation[winner].append(aid)
            desc = (
                f"Asset {aid}: Zero-utility starvation bypass — assigned to "
                f"{winner} (more heirs than assets: {len(heir_ids)} > {len(asset_ids)})"
            )
            tie_breaker_events.append(TieBreakerEvent(
                asset_id=aid,
                tied_heir_ids=list(ordered_heirs),
                points=0,
                winner_heir_id=winner,
                reason="starvation bypass (more heirs than assets)",
                event_description=desc,
            ))

    return SolverResult(
        allocation=existing_allocation,
        mnw_product_value=0.0,
        tie_breaker_events=tie_breaker_events,
    )


def _compute_mnw_product(
    heir_ids: list[str],
    asset_ids: list[str],
    valuations: dict[str, dict[str, int]],
    allocation: dict[str, list[str]],
) -> float:
    """Compute the product of each heir's total utility (MNW product value)."""
    product = 1.0
    for hid in heir_ids:
        utility = 0.0
        for aid in allocation.get(hid, []):
            utility += float(valuations.get(hid, {}).get(aid, 0))
        product *= utility
    return product