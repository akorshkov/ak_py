"""Test PrettyPrinter """

import unittest

from ak.ppobj import PrettyPrinter


class TestPrettyPrinter(unittest.TestCase):
    """Test PrettyPrinter"""

    def test_simple_usage(self):
        """Test processing of good json-looking object"""
        pp = PrettyPrinter()

        # check that some text produced w/o errors
        s = pp.make_pp_str({"a": 1, "some_name": True, "c": None, "d": [42, "aa"]})

        self.assertIn("some_name", s)
        self.assertIn("42", s)

    def test_printing_notjson(self):
        """Test that PrettyPrinter can handle not-json objects."""
        pp = PrettyPrinter()

        s = pp.make_pp_str(42)
        self.assertIn("42", s)

        s = pp.make_pp_str("some text")
        self.assertIn("some text", s)

        s = pp.make_pp_str(True)
        self.assertIn("True", s)

        s = pp.make_pp_str(None)
        self.assertIn("None", s)

    def test_complex_object(self):
        """Test printing 'complex' object where keys have different types."""
        pp = PrettyPrinter()

        s = pp.make_pp_str({
            "d": {1: 23, "a": 17, "c": [1, 20, 2]},
            "ddd": "aaa",
            "a": 2, "ccc": 80,
            "z": 7,
            3: None
        })
        self.assertIn("ccc", s)
