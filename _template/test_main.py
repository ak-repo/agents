"""Smoke test. Replace with real tests that use fakes, not live API calls."""

import unittest

import main


class SmokeTest(unittest.TestCase):
    def test_main_runs(self):
        main.main()


if __name__ == "__main__":
    unittest.main()
