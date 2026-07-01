"""Dependency-free unit tests for first-session practice launch gating."""

import unittest

from app.practice_workflow import practice_launch_blocker


class PracticeLaunchBlockerTests(unittest.TestCase):
    def test_optional_practice_never_blocks_launch(self):
        self.assertIsNone(
            practice_launch_blocker(
                required=False,
                published=False,
                incomplete_heir_names=["Alex"],
            )
        )

    def test_required_unpublished_practice_blocks_launch(self):
        blocker = practice_launch_blocker(required=True, published=False)
        self.assertIn("Publish the Practice Simulation", blocker)

    def test_incomplete_registered_heirs_are_named(self):
        blocker = practice_launch_blocker(
            required=True,
            published=True,
            incomplete_heir_names=["Alex", "Morgan"],
        )
        self.assertIn("Alex, Morgan", blocker)

    def test_completed_required_practice_allows_launch(self):
        self.assertIsNone(
            practice_launch_blocker(
                required=True,
                published=True,
                incomplete_heir_names=[],
            )
        )


if __name__ == "__main__":
    unittest.main()
