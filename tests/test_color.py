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

        self.assertEqual(
            len(raw_text), len(green_text), f"'{raw_text}' vs '{green_text}'")

        raw_green_str = str(green_text)

        self.assertGreater(
            len(raw_green_str), len(raw_text),
            "raw string should contain not visible escape characters and "
            "must be longer than visible text"
        )

        self.assertEqual(raw_text, green_text.plain_text())

    def test_advanced_scenarios(self):
        """Test other scenarios of ColorFmt usage."""

        raw_text = 'test'

        blink_text = ColorFmt(
            'YELLOW', bg_color='BLUE', bold=True, underline=True,
            blink=True, crossed=True)(raw_text)

        self.assertEqual(len(blink_text), len(raw_text))
        self.assertGreater(len(str(blink_text)), len(raw_text))
        self.assertEqual(blink_text.plain_text(), raw_text)

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
        """Test ColoredText which does not have any effect."""
        raw_text = 'text'
        nocolor_text = ColorFmt(None)(raw_text)

        self.assertEqual(len(raw_text), len(nocolor_text))
        self.assertEqual(raw_text, nocolor_text.plain_text())
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
        self.assertEqual(raw_text, orig.plain_text())

        t = ColoredText(orig, "some more")
        self.assertEqual(raw_text, orig.plain_text())

        other_t = ColorFmt('GREEN')("other text")
        t = ColoredText(other_t, orig)
        self.assertEqual(raw_text, orig.plain_text())
        t = ColoredText(orig, other_t)
        self.assertEqual(raw_text, orig.plain_text())

        t = ColoredText(orig)
        t += other_t
        self.assertEqual(raw_text, orig.plain_text())

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

        self.assertTrue(green_text.plain_text() == raw_text)
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
        self.assertEqual("p1", part_1.plain_text())
        self.assertEqual("p2", part_2.plain_text())

        t = ColoredText(part_1, part_2)
        self.assertTrue(t == expected)

        t = ColoredText(part_1)
        t += part_2
        self.assertTrue(t == expected)

    def test_join(self):
        """Test ColoredText.join method."""

        sep = ColorFmt('GREEN')('=')

        empty = sep.join([])
        self.assertEqual("", empty.plain_text())

        parts = [
            ColorFmt('RED')('red'),
            "white",
        ]

        joined = sep.join(parts)
        self.assertEqual("red=white", joined.plain_text())

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

    def test_slicing(self):
        """Test slising of ColoredText."""

        # ColoredText to be used in tests
        text = ColorFmt('GREEN')('green') + ColorFmt('RED')('red')
        self.assertEqual(8, len(text))
        self.assertEqual("greenred", text.plain_text())

        # 1. test simple indexing (1 character)
        green_fmt = ColorFmt('GREEN')
        red_fmt = ColorFmt('RED')

        # 1.1. positive indexes
        self.assertEqual(green_fmt('g'), text[0])
        self.assertEqual('g', text[0].plain_text())

        self.assertEqual(green_fmt('e'), text[2])
        self.assertEqual('e', text[2].plain_text())

        self.assertEqual(red_fmt('r'), text[5])
        self.assertEqual('r', text[5].plain_text())

        self.assertEqual(red_fmt('d'), text[7])
        self.assertEqual('d', text[7].plain_text())

        for index in [8, 9, 100]:
            with self.assertRaises(IndexError) as exc:
                text[index]
            err_msg = str(exc.exception)
            self.assertIn(str(index), err_msg)
            self.assertIn("out of range", err_msg)

        # 1.2. negative indexes
        self.assertEqual(green_fmt('g'), text[-8])
        self.assertEqual('g', text[-8].plain_text())

        self.assertEqual(green_fmt('e'), text[-6])
        self.assertEqual('e', text[-6].plain_text())

        self.assertEqual(red_fmt('r'), text[-3])
        self.assertEqual('r', text[-3].plain_text())

        self.assertEqual(red_fmt('d'), text[-1])
        self.assertEqual('d', text[-1].plain_text())

        for index in [-9, -100]:
            with self.assertRaises(IndexError) as exc:
                text[index]
            err_msg = str(exc.exception)
            self.assertIn(str(index), err_msg)
            self.assertIn("out of range", err_msg)

        # 1.3. invalid type of index
        for index in ["5", 3.3, None]:
            with self.assertRaises(ValueError) as exc:
                text[index]
            err_msg = str(exc.exception)
            self.assertIn(str(index), err_msg)
            self.assertIn("Unexpected index value", err_msg)

        # 2. slices

        # 2.1. normal substrings, positive indexes
        self.assertEqual(text, text[0:8])
        self.assertEqual(text, text[0:9], "index.stop > text length, but it's ok")
        self.assertEqual(green_fmt("ree"), text[1:4])
        self.assertEqual(green_fmt("reen"), text[1:5])
        self.assertEqual(green_fmt("reen") + red_fmt("r"), text[1:6])

        # 2.2. empty substrings, positive indexes
        empty_text = ColorFmt(None)("")
        empty_text = ColoredText()
        self.assertEqual(empty_text, text[0:0])
        self.assertEqual(empty_text, text[1:1])
        self.assertEqual(empty_text, text[5:5])
        self.assertEqual(empty_text, text[6:6])
        self.assertEqual(empty_text, text[8:8])

        self.assertEqual(empty_text, text[5:4])

        self.assertEqual(empty_text, text[100:100])
        self.assertEqual(empty_text, text[100:1])

        # 2.3. normal substrings, negative indexes
        self.assertEqual(text, text[-8:8])
        self.assertEqual(text, text[-9:9])
        self.assertEqual("reenred", text[-7:8].plain_text())
        self.assertEqual("reenre", text[1:-1].plain_text())

        # 2.4. empty substrings, negative indexes
        self.assertEqual(empty_text, text[-1:-1])
        self.assertEqual(empty_text, text[-100:-100])
        self.assertEqual(empty_text, text[5:-5])
        self.assertEqual(empty_text, text[-1:1])

        # 3. slises with missing start/stop values
        self.assertEqual(text, text[:])
        self.assertEqual(text, text[0:])
        self.assertEqual("reenred", text[1:].plain_text())
        self.assertEqual("greenre", text[:-1].plain_text())

        # make sure nothing happened with original text we used in tests
        self.assertEqual(8, len(text))
        self.assertEqual("greenred", text.plain_text())

    def test_slising_empty_text(self):
        """make sure slicing does not fail with empty text."""
        empty_text = ColoredText()
        also_empty_text = ColorFmt(None)("")

        self.assertEqual(empty_text, also_empty_text)

        self.assertEqual(empty_text, empty_text[:])
        self.assertEqual(empty_text, empty_text[1:1])
        self.assertEqual(empty_text, empty_text[1:10])
        self.assertEqual(empty_text, empty_text[10:1])
        self.assertEqual(empty_text, empty_text[1:-1])

    def test_fixed_len_method(self):
        """Test ColoredText.fixed_len method"""
        t = ColorFmt('RED')("123") + ColorFmt('BLUE')("456")

        # get longer result
        result = t.fixed_len(10)
        self.assertEqual(10, len(result))
        self.assertEqual(
            t.plain_text(), "123456", "original object should not be modified")
        self.assertEqual(result.plain_text(), "123456    ")

        # get shorted result
        result = t.fixed_len(5)
        self.assertEqual(5, len(result))
        self.assertEqual(
            t.plain_text(), "123456", "original object should not be modified")
        self.assertEqual(result.plain_text(), "12345")

    def test_strip_colors(self):
        """test method which removes color sequences from string."""

        color_text = ColorFmt('GREEN')('Green') + ColorFmt('RED')('Red')

        plain_str = 'GreenRed'
        colored_str = str(color_text)

        self.assertNotEqual(
            plain_str, colored_str,
            f"'{plain_str}' should not be equal to '{colored_str}' because "
            f"of color sequences")
        self.assertTrue(len(colored_str) > len(plain_str))

        stripped_colored_str = ColoredText.strip_colors(colored_str)
        self.assertEqual(plain_str, stripped_colored_str)


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
