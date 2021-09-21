"""Test ColorFmt and ColorTest"""

import unittest

from ak.color import ColoredText, ColorFmt, ColorBytes


class TestColorFmt(unittest.TestCase):
    """Test ColorFmt: object wich produce colored text."""

    def test_simple_usage(self):
        """Test successfull scenarios of using ColorFmt."""
        green_printer = ColorFmt('GREEN')
        raw_text = 'test'
        green_text = green_printer(raw_text)

        self.assertEqual(len(raw_text), len(green_text))

        raw_green_str = str(green_text)

        self.assertGreater(
            len(raw_green_str), len(raw_text),
            "raw string should contain not visible escape characters and "
            "must be longer than visible text"
        )

        self.assertEqual(raw_text, green_text.no_color())

    def test_advanced_scenarios(self):
        """Test other scenarios of ColorFmt usage."""

        raw_text = 'test'

        blink_text = ColorFmt(
            'YELLOW', bg_color='BLUE', bold=True, underline=True,
            blink=True, crossed=True)(raw_text)

        self.assertEqual(len(blink_text), len(raw_text))
        self.assertGreater(len(str(blink_text)), len(raw_text))
        self.assertEqual(blink_text.no_color(), raw_text)

    def test_dummy_printer_construction(self):
        """Test possibility to turn-off coloring effects."""

        raw_text = 'test'

        dummy_printer = ColorFmt(
            'YELLOW', bg_color='BLUE', bold=True, underline=True,
            blink=True, crossed=True, use_effects=False)

        t = dummy_printer(raw_text)

        self.assertEqual(
            raw_text, t,
            "'t' should have no special effects as ColorFmt "
            "was created with 'use_effects = False'")

    def test_wrong_color(self):
        with self.assertRaises(ValueError) as exc:
            ColorFmt('BAD_COLOR')

        err_msg = str(exc.exception)
        self.assertIn("Invalid color name", err_msg)
        self.assertIn("BAD_COLOR", err_msg)
        self.assertIn(
            'MAGENTA', err_msg,
            "error message should contain list of valid color codes",
        )

        with self.assertRaises(ValueError) as exc:
            ColorFmt(None, bg_color='BAD_COLOR')

        err_msg = str(exc.exception)
        self.assertIn("Invalid bg_color name", err_msg)
        self.assertIn("BAD_COLOR", err_msg)
        self.assertIn(
            'MAGENTA', err_msg,
            "error message should contain list of valid color codes",
        )

    def test_make_colored_fmt(self):
        """Text ColorFmt.make method."""

        # Check that the 'make' method does not fail with different
        # types of arguents.
        _ = ColorFmt.make(None)  # produces dummy formatter
        _ = ColorFmt.make('GREEN')
        _ = ColorFmt.make(('GREEN', {'bold': True}))
        _ = ColorFmt.make((None, {'bold': True}))
        _ = ColorFmt.make('GREEN', use_colors=False)


class TestColoredTextProperties(unittest.TestCase):

    def test_nocolor_text(self):
        raw_text = 'text'
        nocolor_text = ColorFmt(None)(raw_text)

        self.assertEqual(len(raw_text), len(nocolor_text))
        self.assertEqual(raw_text, nocolor_text.no_color())
        self.assertEqual(raw_text, str(nocolor_text))

    def test_empty_constructor(self):
        """Test behavior of empty constructor."""
        t = ColoredText()

        self.assertEqual(0, len(t))
        self.assertEqual("", str(t))

        t += "aaa"

        self.assertEqual("aaa", str(t))

    def test_making_copies(self):
        """Make sure operations with the copy no not affect original."""
        raw_text = "some_text"
        orig = ColorFmt('GREEN')(raw_text)

        t = ColoredText(orig)
        self.assertEqual(raw_text, orig.no_color())

        t = ColoredText(orig, "some more")
        self.assertEqual(raw_text, orig.no_color())

        other_t = ColorFmt('GREEN')("other text")
        t = ColoredText(other_t, orig)
        self.assertEqual(raw_text, orig.no_color())
        t = ColoredText(orig, other_t)
        self.assertEqual(raw_text, orig.no_color())

        t = ColoredText(orig)
        t += other_t
        self.assertEqual(raw_text, orig.no_color())

    def test_equality_check(self):
        """ColoredText objects are equal if have same text and same color.

        ColoredText with no color considered equal to raw string.
        """
        raw_text = "text"
        green_text = ColorFmt('GREEN')(raw_text)
        green_text1 = ColorFmt('GREEN')(raw_text)
        red_text = ColorFmt('RED')(raw_text)
        nocolor_text = ColorFmt(None)(raw_text)

        self.assertTrue(green_text == green_text)
        self.assertTrue(green_text == green_text1)
        self.assertFalse(green_text != green_text)
        self.assertFalse(green_text != green_text1)

        self.assertTrue(
            green_text != red_text,
            "even though printable characters are the same, "
            "green text and red text are considered different.")

        self.assertTrue(green_text.no_color() == raw_text)
        self.assertTrue(green_text != raw_text)

        self.assertTrue(green_text != nocolor_text)

        # special case: ColoredText with no color considered equal to raw string
        self.assertTrue(raw_text == nocolor_text)
        self.assertTrue(nocolor_text == raw_text)

    def test_concatenation(self):
        """Text different ways to concatenate ColoredText."""

        part_1 = ColorFmt('GREEN')("p1")
        part_2 = ColorFmt('GREEN')("p2")

        t = part_1 + part_2
        expected = ColorFmt('GREEN')("p1p2")

        self.assertTrue(t == expected)
        self.assertEqual("p1", part_1.no_color())
        self.assertEqual("p2", part_2.no_color())

        t = ColoredText(part_1, part_2)
        self.assertTrue(t == expected)

        t = ColoredText(part_1)
        t += part_2
        self.assertTrue(t == expected)

    def test_formatting(self):
        """Test string formatting of ColoredText objects"""

        t = ColorFmt('GREEN')("text")

        # just check formatting produce no errors
        s = f"{t}"        # printed as "text"
        s = f"{t:s}"      # same, 's' format specifier is optional
        s = f"{t:10}"     # printed as "text      "
        s = f"{t:>10}"    # printed as "      text"
        s = f"{t:>>10}"   # printed as ">>>>>>text"

        # test bad format strings
        with self.assertRaises(ValueError) as exc:
            f"{t:d}"

        err_msg = str(exc.exception)
        self.assertIn("invalid format type 'd'", err_msg)

        with self.assertRaises(ValueError) as exc:
            f"{t:1a0}"

        err_msg = str(exc.exception)
        self.assertIn("invalid width '1a0'", err_msg)


class TestColorFmtBytes(unittest.TestCase):
    """Test using ColorFmt to process bytes."""

    def test_simple_with_bytes(self):
        """Test successfull scenarios of using ColorFmt with bytes."""

        green_printer_b = ColorBytes('GREEN')
        raw_bytes = b'test'
        green_bytes = green_printer_b(raw_bytes)

        self.assertGreater(
            len(green_bytes), len(raw_bytes),
            f"formatte bytes should contain additional escape "
            f"characters: {green_bytes}")

        with self.assertRaises(TypeError) as err:
            green_printer_b("string_text")
