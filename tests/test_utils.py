"""Test miscelaneous utils of ak package"""

import unittest

from ak.utils import Comparable


class TestComparabe(unittest.TestCase):
    """Test Comparable mixin"""

    def test_comparisons(self):
        """Test comparisons of objects with custom comparisons rules."""

        class CObj(Comparable):
            """Objects of this class are compared by last digit of val attribute."""
            def __init__(self, val):
                self.val = val

            def cmp(self, other):
                """Method which implements comparison by last digit."""
                return self.val % 10 - other.val % 10

        self.assertTrue(CObj(3) == CObj(33))
        self.assertTrue(CObj(0) == CObj(10))

        self.assertTrue(CObj(5) > CObj(54))
        self.assertTrue(CObj(5) >= CObj(54))

        self.assertTrue(CObj(92) < CObj(3))
        self.assertTrue(CObj(92) <= CObj(3))

        self.assertTrue(CObj(25) !=  CObj(42))
