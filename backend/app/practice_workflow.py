"""Pure workflow rules for the registered-heir practice phase.

Kept dependency-free so launch gating can be verified without importing the
full FastAPI/solver application stack.
"""

from __future__ import annotations

from collections.abc import Iterable


def practice_launch_blocker(
    *,
    required: bool,
    published: bool,
    incomplete_heir_names: Iterable[str] = (),
) -> str | None:
    """Return the user-facing launch blocker, or None when launch may proceed."""
    if not required:
        return None
    if not published:
        return (
            "Publish the Practice Simulation before launching the real allocation, "
            "or mark practice optional in the simulation manager."
        )
    names = [name for name in incomplete_heir_names if name]
    if names:
        return (
            "Practice allocation is still required for: "
            f"{', '.join(names)}. Wait for completion or mark practice optional."
        )
    return None
