"""Test ColorFmt and ColorTest"""

import unittest
import io
from typing import Iterator

from ak.color import (
    ColoredText, SHText, ColorFmt, ColorBytes, Palette, ColorsConfig, PaletteUser,
    get_global_colors_config, set_global_colors_config,
    sh_fmt, sh_print,
)


#########################
# Test ColorFmt

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

    def test_numeric_colors(self):
        """Test using numeric color ids."""

        test_text = "Some Test Text"

        fmt1 = ColorFmt((4, 1, 1), bold=True)
        fmt2 = ColorFmt(167, bold=True)

        t1 = fmt1(test_text)
        t2 = fmt2(test_text)

        s1 = str(t1)
        s2 = str(t2)

        # color (4, 1, 1) is the same as color 167:
        # 16 + 4*36 + 6 + 1 = 167
        self.assertEqual(s1, s2, f"{s1!r} != {s2!r}")

        self.assertNotEqual(test_text, s1)

        self.assertEqual(test_text, t1.plain_text())

    def test_grayscale_colors(self):
        """Test grayscale colors."""
        test_text = "Some Test Text"

        fmt1 = ColorFmt("g5", bold=True)
        fmt2 = ColorFmt(237, bold=True)

        t1 = fmt1(test_text)
        t2 = fmt2(test_text)

        s1 = str(t1)
        s2 = str(t2)

        # color 'g5' is the same as color 237: 232 + 5 = 237
        self.assertEqual(s1, s2, f"{s1!r} != {s2!r}")

        self.assertNotEqual(test_text, s1)

        self.assertEqual(test_text, t1.plain_text())

    def test_invalid_intcolors(self):
        """Test construction of ColorFmt with invalid colors."""

        expected_errors = [
            (-5, "Invalid int color id -5"),
            (256, "Invalid int color id 256"),
            ('g25', "Invalid 'shade of gray' color description 'g25'"),
            ((1, 1, 6), "Invalid color description tuple"),
            ((1, 1), "Invalid color description tuple"),
        ]

        for arg, expected_msg in expected_errors:
            with self.assertRaises(ValueError) as err:
                ColorFmt(arg)

            err_msg = str(err.exception)
            self.assertIn(expected_msg, err_msg)


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
        _ = f"{t}"        # printed as "text"
        _ = f"{t:s}"      # same, 's' format specifier is optional
        _ = f"{t:10}"     # printed as "text      "
        _ = f"{t:>10}"    # printed as "      text"
        _ = f"{t:>>10}"   # printed as ">>>>>>text"

        # test bad format strings
        with self.assertRaises(ValueError) as exc:
            _ = f"{t:d}"

        err_msg = str(exc.exception)
        self.assertIn("invalid format type 'd'", err_msg)

        with self.assertRaises(ValueError) as exc:
            _ = f"{t:1a0}"

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
                _ = text[index]
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


#########################
# Test Palette and ColorsConfig functionality

class TestPalette(unittest.TestCase):
    """Test Palette functionality."""

    def test_palette(self):
        palette = Palette({
            'style_1': ColorFmt('GREEN'),
            'style_2': ColorFmt('BLUE'),
        })

        t0 = palette.get_color('style_1')("test text")
        t1 = palette['style_1']("test text")

        self.assertEqual(t0, t1)

        # unknown style does not raise error
        t2 = palette['unknown_style']("test text")
        self.assertEqual("test text", str(t2))

    def test_color_text_creation(self):
        """Test palette producing ColoredText"""
        palette = Palette({
            'style_1': ColorFmt('GREEN'),
            'style_2': ColorFmt('BLUE'),
        })

        # single arguments of different types
        self.assertEqual(
            palette(('unknown', 'text0')), ColorFmt.get_plaintext_fmt()('text0'))

        self.assertEqual(
            palette(('style_1', 'text1')), ColorFmt('GREEN')('text1'))

        self.assertEqual(
            palette(['style_2', 'text2']), ColorFmt('BLUE')('text2'))

        self.assertEqual(
            palette('plain'), ColorFmt.get_plaintext_fmt()('plain'))

        self.assertEqual(
            palette(ColorFmt('RED')('red')), ColorFmt('RED')('red'))

        self.assertEqual(
            palette(), ColorFmt.get_plaintext_fmt()(''))

        # and combination of several arguments of different types
        t0 = palette(
            'plain ',
            ('style_1', 'text1'),
            ' ',
            ['style_1', 'text2'],
            ' ',
            ColorFmt('RED')('red'))

        self.assertEqual('plain text1 text2 red', t0.plain_text())

    def test_palette_self_report(self):
        """Palette can print itself."""
        palette = Palette({
            'style_1': ColorFmt('GREEN'),
            'style_2': ColorFmt('BLUE'),
        })

        report = palette.make_report()
        lines = report.split('\n')
        self.assertEqual(2, len(lines))
        self.assertIn('style_1', report)


class TestSHText(unittest.TestCase):
    """Test SHText"""

    def test_basic_sh_text_functionality(self):
        """Test basic functionality of SHText"""

        sh_descr = SHText("Some ", ("SYNTAX", "text"), " to test")

        # SHText does not know actual colors corresponding to
        # syntax regions, so conversion to str produces plain text
        self.assertEqual("Some text to test", str(sh_descr))
        self.assertEqual("Some text to test", sh_descr.plain_text())

        # use palette to create ColoredText
        palette = Palette({"SYNTAX": ColorFmt('GREEN')})
        ct = palette(sh_descr)
        ct_expected = ColoredText(
            "Some ",
            ColorFmt('GREEN')("text"),
            " to test")
        self.assertEqual(
            ct_expected, ct,
            f"{ct_expected} != {ct}",
        )

        # unknown syntax name should not raise error
        palette = Palette({})
        ct = palette(sh_descr)
        self.assertEqual("Some text to test", str(ct))

    def test_sh_text_basic_propertirs(self):
        """SHText corner cases."""

        # empty constructior => empty result
        sh_descr = SHText()

        self.assertEqual("", str(sh_descr))

        palette = Palette({"SYNTAX": ColorFmt('GREEN')})
        self.assertEqual("", palette(sh_descr))


class TestColorsConfig(unittest.TestCase):

    class TstColorsConfig(ColorsConfig):
        # not a nice-loking colors config, but ok for test purposes
        DFLT_CONFIG = {
            "TEXT": "",
            "NAME": "BLUE:bold",
            "VERY_COLORED": "YELLOW/BLUE:bold,faint,underline,blink,crossed",
            "VERY_UNCOLORED": (
                "YELLOW/BLUE:no_bold,no_faint,no_underline,no_blink,no_crossed"
            ),
            "TABLE": {
                "BORDER": "RED",
                "NAME": "GREEN",
                "ALT1_NAME": "NAME",
                "ALT2_NAME": "TABLE.NAME",
            },
        }

    def test_colors_config_use_defaults(self):
        """Test initialization of ColorsConfig with all defaults."""

        raw_text = "test"

        # reset possible previous initialization
        set_global_colors_config(None)

        # get_color should not fail even without explicit initialization
        _ = get_global_colors_config().get_color("TEXT")

        # explicit initialization with using all the defaults
        colors_conf = self.TstColorsConfig()

        colored_texts = {
            syntax_name: colors_conf.get_color(syntax_name)(raw_text)
            for syntax_name in [
                "TEXT", "NAME", "VERY_COLORED", "VERY_UNCOLORED",
                "UNEXPECTED",
                "TABLE.BORDER", "TABLE.NAME", "TABLE.ALT1_NAME", "TABLE.ALT2_NAME",
            ]
        }

        self.assertEqual(
            raw_text, colored_texts['TEXT'], "empty description means no formatting")
        self.assertEqual(
            raw_text, colored_texts['UNEXPECTED'],
            "missing syntax means no formatting")

        #print(colored_texts['VERY_COLORED'])
        #print(colored_texts['VERY_UNCOLORED'])

        # all these items expected to be colored
        self.assertGreater(len(str(colored_texts['NAME'])), len(raw_text))
        self.assertGreater(len(str(colored_texts['TABLE.NAME'])), len(raw_text))
        self.assertGreater(len(str(colored_texts['TABLE.ALT1_NAME'])), len(raw_text))
        self.assertGreater(len(str(colored_texts['TABLE.ALT2_NAME'])), len(raw_text))

        self.assertEqual(
            colored_texts['NAME'], colored_texts['TABLE.ALT1_NAME'])
        self.assertEqual(
            colored_texts['TABLE.NAME'], colored_texts['TABLE.ALT2_NAME'])
        self.assertNotEqual(
            colored_texts['NAME'], colored_texts['TABLE.ALT2_NAME'],
            "expected BLUE and GREEN colors respectively")

    def test_no_colors_config(self):
        """Test turning off all the syntax coloring."""

        raw_text = "test"

        colors_conf = self.TstColorsConfig({}, use_effects=False)

        colored_texts = {
            syntax_name: colors_conf.get_color(syntax_name)(raw_text)
            for syntax_name in [
                "TEXT", "NAME", "VERY_COLORED", "VERY_UNCOLORED",
                "UNEXPECTED",
                "TABLE.BORDER", "TABLE.NAME", "TABLE.ALT1_NAME", "TABLE.ALT2_NAME",
            ]
        }

        for syntax_name, text in colored_texts.items():
            self.assertEqual(
                raw_text, text, "should be equal as all the coloring was turned off")

    def test_config_not_default(self):
        """Test modifications to default config."""

        raw_text = "test"

        colors_conf = self.TstColorsConfig({
            'TABLE': {
                'NAME': "",
            },
            'VERY_COLORED': "TABLE.BORDER",
        })

        colored_texts = {
            syntax_name: colors_conf.get_color(syntax_name)(raw_text)
            for syntax_name in [
                "TEXT", "NAME", "VERY_COLORED", "VERY_UNCOLORED",
                "UNEXPECTED",
                "TABLE.BORDER", "TABLE.NAME", "TABLE.ALT1_NAME", "TABLE.ALT2_NAME",
            ]
        }

        self.assertEqual(
            raw_text, colored_texts['TABLE.NAME'],
            "syntax coloring was tuned off for TABLE.NAME")
        self.assertEqual(
            colored_texts['VERY_COLORED'], colored_texts['TABLE.BORDER'])

    def test_config_multiple_extras(self):
        """Test ColorsConfig construction with multiple extra_rules."""
        extra_rules_01 = {
            'TABLE': {
                'NAME': "CYAN",
                'BORDER': "NAME",  # "BLUE:bold"
            },
            'VERY_COLORED': "TABLE.NAME",
        }
        extra_rules_02 = {
            'TABLE': {
                'NAME': "YELLOW",
            },
        }

        colors_conf = self.TstColorsConfig(extra_rules_01, extra_rules_02)

        raw_text = "test"

        self.assertEqual(
            str(colors_conf.get_color('TABLE.NAME')(raw_text)),
            str(ColorFmt("YELLOW")(raw_text)),
            "'YELLOW' is apecified in extra_rules_02")

        self.assertEqual(
            str(colors_conf.get_color('TABLE.BORDER')(raw_text)),
            str(ColorFmt("BLUE", bold=True)(raw_text)),
            "'BLUE:bold' is taken from TstColorsConfig.DFLT_CONFIG['NAME'] "
            "as specified in extra_rules_01")

        # first all specified rules are combined, after that rules resolved
        self.assertEqual(
            str(colors_conf.get_color('VERY_COLORED')(raw_text)),
            str(ColorFmt("YELLOW")(raw_text)),
            "'VERY_COLORED' -> extra_rules_01 -> 'TABLE.NAME' -> "
            " extra_rules_02 -> 'YELLOW'")

    def test_config_make_palette(self):
        """Test Palette creation by ColorsConfig."""
        extra_rules_01 = {
            'TABLE': {
                'NAME': "CYAN",
                'BORDER': "NAME",  # "BLUE:bold"
                'EXTRA': "YELLOW:bold",
            },
            'VERY_COLORED': "TABLE.NAME",
        }
        extra_rules_02 = {
            'TABLE': {
                'NAME': "YELLOW",
            },
        }
        colors_conf = self.TstColorsConfig(extra_rules_01, extra_rules_02)

        raw_text = "test"

        # palette for printing tables
        palette_table = colors_conf.make_palette('TABLE')
        self.assertEqual(
            # these colors are specified in TstColorsConfig and extra_rules_01
            {'BORDER', 'NAME', 'ALT1_NAME', 'ALT2_NAME', 'EXTRA'},
            palette_table.colors.keys()
        )

        self.assertEqual(
            str(palette_table(('NAME', raw_text))),
            str(ColorFmt('YELLOW')(raw_text)),
            # 'YELLOW' is specified for 'TABLE.NAME' in extra_rules_02
        )

        self.assertEqual(
            str(palette_table(('ALT2_NAME', raw_text))),
            str(ColorFmt('YELLOW')(raw_text)),
            # 'ALT2_NAME' -> 'TABLE.NAME' -> 'YELLOW'
        )

    def test_make_palette_extra_colors(self):
        """Test creation of Palette with extra colors"""
        colors_conf = self.TstColorsConfig()
        palette = colors_conf.make_palette(
            'TABLE',
            VERY_COLORED='VERY_COLORED',
            BORDER='NAME',
        )

        self.assertIn(
            'VERY_COLORED', palette.colors,
            "present in palette only because explicitely specified for make_palette"
        )

        sample = "sample"
        self.assertEqual(
            str(colors_conf.get_color('NAME')(sample)),
            str(palette.get_color('BORDER')(sample)),
        )
        self.assertNotEqual(
            str(colors_conf.get_color('TABLE.BORDER')(sample)),
            str(palette.get_color('BORDER')(sample)),
            "'BORDER' syntax is expected to be overridden"
        )

    def test_make_palette_all_colors(self):
        """Test ceation of Palette containing all colors from config"""
        colors_conf = self.TstColorsConfig()

        palette_all = colors_conf.make_palette()
        all_syntaxes = palette_all.colors.keys()
        self.assertIn('TEXT', all_syntaxes)
        self.assertIn('VERY_COLORED', all_syntaxes)
        self.assertIn('TABLE.BORDER', all_syntaxes)

    def test_palette_user_class_init_palette(self):
        """Test behavior of a class which uses palette and global colors config."""

        # 0. make primitive PaletteUser class and object of this class
        class CPrinter(PaletteUser):
            """Primitive class which produces colored text and reads colors config."""

            @classmethod
            def _init_palette(cls, color_config):
                # create palette to be used by objects of this class
                # colors config is taken form ak.color.ColorsConfig
                return Palette({
                    'SYNTAX1': color_config.get_color('TABLE.COL_TITLE'),
                    'BAD_SYNTAX': color_config.get_color('UNKNOWN_SYNTAX'),
                })

            def __init__(self, raw_text):
                self.raw_text = raw_text
                self.palette = self.get_palette()

            def mk_colored_texts(self):
                return {
                    'SYNTAX1': self.palette['SYNTAX1'](self.raw_text),
                    'BAD_SYNTAX': self.palette['BAD_SYNTAX'](self.raw_text),
                }

        # it is supposed that global color config is initialized only once.
        # manually clean-up config to reset the init
        set_global_colors_config(None)
        CPrinter._PALETTE = None

        raw_text = "test"

        cp = CPrinter(raw_text)
        colored_texts = cp.mk_colored_texts()

        self.assertGreater(
            len(str(colored_texts['SYNTAX1'])), len(raw_text),
            "expected to be colored: color taken from 'TABLE.COL_TITLE' of config",
        )
        self.assertEqual(
            raw_text,
            ColoredText.strip_colors(str(colored_texts['SYNTAX1'])))

        self.assertEqual(raw_text, str(colored_texts['BAD_SYNTAX']))

        # it is supposed that global color config is initialized only once.
        # manually clean-up config to reset the init
        set_global_colors_config(None)
        CPrinter._PALETTE = None

        # test init config with all color effects turned off
        set_global_colors_config(self.TstColorsConfig({}, use_effects=False))

        cp = CPrinter(raw_text)
        colored_texts = cp.mk_colored_texts()

        self.assertEqual(raw_text, str(colored_texts['SYNTAX1']))
        self.assertEqual(raw_text, str(colored_texts['BAD_SYNTAX']))

    def test_palette_user_class_with_specified_syntax_group(self):
        """Test behavior of a class which creates palette based on syntax group."""

        # reset possible previous initialization
        set_global_colors_config(None)

        # 0. make primitive PaletteUser class and object of this class
        class CPrinter(PaletteUser):
            """Primitive class which uses Palette created from global config."""
            _SYNTAX_GROUP = 'TABLE'

            def get_my_palette(self):
                """just return own Palette for further experiments"""
                return self.c_fmt()

        cp = CPrinter()
        palette = cp.get_my_palette()

        # created palette is created from global ColorsConfig
        # default ColorsConfig may be changed in future, so this test
        # checks only very basic properties of the created palette.
        self.assertIsInstance(palette, Palette)

        syntax_names = palette.colors.keys()

        self.assertIn('BORDER', syntax_names)
        self.assertIn('COL_TITLE', syntax_names)

        self.assertNotIn('TABLE.BORDER', syntax_names)
        self.assertNotIn('FUNC_NAME', syntax_names)

    def test_config_report(self):
        """Smoke test that make_report doesn't fail."""

        colors_conf = self.TstColorsConfig({})
        _ = colors_conf.make_report()

        colors_conf = self.TstColorsConfig({}, use_effects=False)
        _ = colors_conf.make_report()


class TestGlobalColorsFormattingMethods(unittest.TestCase):
    """Test global methods for processing syntax-highlighted text"""

    class TstColorsConfig(ColorsConfig):
        # not a nice-loking colors config, but ok for test purposes
        DFLT_CONFIG = {
            "TEXT": "",
            "NAME": "BLUE:bold",
            "DESCR": "YELLOW",
        }

    class _DummySHTextGenerator:
        def __init__(self, *sh_lines):
            self._sh_lines = sh_lines

        def sh_lines(self) -> Iterator[SHText]:
            yield from self._sh_lines

        def sh_text(self) -> SHText:
            return SHText("\n").join(self._sh_lines)

    def test_global_color_conf_usage(self):
        """Test setting of global color config.

        sh_fmt global function uses it, so we will use this function for test.
        """

        blue_colors_conf = self.TstColorsConfig()
        red_colors_conf = self.TstColorsConfig({'NAME': "RED"})

        sample_plain_text = "sample text"
        sample_sh_text = SHText(("NAME", sample_plain_text))

        # 1. global config contains colors
        set_global_colors_config(blue_colors_conf)

        blue_ct = sh_fmt(sample_sh_text)
        self.assertIsInstance(blue_ct, ColoredText)
        self.assertEqual(blue_ct.plain_text(), sample_plain_text)
        self.assertNotEqual(
            str(blue_ct), sample_plain_text,
            "blue_ct object is expected to contain color sequences because "
            "the global config contains some color configuration for "
            "the 'NAME' syntax group")

        # 2. palette is explicitley specified for sh_fmt
        red_ct = sh_fmt(sample_sh_text, palette=red_colors_conf.make_palette())
        self.assertIsInstance(red_ct, ColoredText)
        self.assertEqual(red_ct.plain_text(), sample_plain_text)
        self.assertNotEqual(
            str(blue_ct), str(red_ct),
            "even though the global color config is still the same, "
            "different palette was used to prepare the red_ct, so "
            "different color sequences are expected")

        # 3. set different gobal colors
        set_global_colors_config(red_colors_conf)
        new_red_ct = sh_fmt(sample_sh_text)
        self.assertEqual(
            str(new_red_ct), str(red_ct),
            "according to the global config the sample_sh_text now should be red")

        # reset global golors config
        set_global_colors_config(None)

    def test_sh_fmt_method(self):
        """sh_fmt - converts single argument into ColoredText."""

        # test misc types of arguments the sh_fmt accepts
        # 1. SHText
        sample_text = "sample text"
        ct = sh_fmt(SHText(("NAME", sample_text)))
        self.assertEqual(ct.plain_text(), sample_text)
        self.assertNotEqual(str(ct), sample_text)

        # 2. simple string
        ct = sh_fmt(sample_text)
        self.assertEqual(ct.plain_text(), sample_text)
        self.assertEqual(str(ct), sample_text)

        # 3. SHText generator
        obj_with_shtext_descr = self._DummySHTextGenerator(
            SHText(("NAME", "usual")),
            SHText(("CATEGORY", "description")),
        )
        ct = sh_fmt(obj_with_shtext_descr)
        self.assertEqual(ct.plain_text(), "usual\ndescription")

        # 4. other types should be treated as strings
        x = ("NAME", "name")
        ct = sh_fmt(x)
        self.assertIsInstance(ct, ColoredText)
        # even though the argument looks like a colored chunk argument of SHText,
        # it should not be interpreted as colored text. It's just a tuple.
        # So, the result should be '("NAME", "name")' or "('NAME', 'name')"
        self.assertEqual(ct.plain_text(), str(x))

    def test_sh_print_method(self):
        """Test sh_print function."""

        # 1. print simple string
        with io.StringIO() as output:
            sh_print("sample", file=output)
            result = output.getvalue()
        self.assertEqual(result, "sample\n")

        # 2. print SHText object
        with io.StringIO() as output:
            sh_print(SHText(("NAME", "test name text")), file=output)
            result = output.getvalue()
        self.assertIn("test name text", result)
        self.assertNotEqual(result, "test name text\n")  # color sequences expected

        # 3. print SHText generator
        obj_with_shtext_descr = self._DummySHTextGenerator(
            SHText(("NAME", "usual")),
            SHText(("CATEGORY", "description")),
        )
        with io.StringIO() as output:
            sh_print(obj_with_shtext_descr, file=output)
            result = output.getvalue()
        # obj description consists of 2 lines.
        # each line ends with '\n'
        lines = result.split('\n')
        self.assertEqual(len(lines), 3)
        self.assertIn("usual", lines[0])
        self.assertIn("description", lines[1])
        self.assertEqual(lines[2], "")

        # 4. print several items
        with io.StringIO() as output:
            sh_print(
                "item1",
                "item2",
                SHText(("NAME", "name")),
                obj_with_shtext_descr,
                SHText(("NUMBER", "25")),
                file=output)
            result = output.getvalue()

        plain_text_result = ColoredText.strip_colors(result)
        # all printed items are separated by ' ', obj_with_shtext_descr
        # consists of two lines, so the result also consists of two lines
        expected_text = (
            "item1 item2 name usual\n"
            "description 25\n")
        self.assertEqual(plain_text_result, expected_text)

        # 5. make sure other objects are can be printed
        # (the same way standard 'print' prints them)

        # 5.1. this item looks like a syntax group of SHText.
        # But it must not be interpreted as colored text, it should be printed
        # as a simple tuple.
        x = ("NAME", "name")

        with io.StringIO() as output:
            sh_print(x, file=output)
            result = output.getvalue()

        self.assertEqual(result, f"{x}\n")

        # 5.2. test printing miscellaneous other objects

        items_to_print = [
            [],
            {},
            "text",
            "",
            ("NAME", "name"),
            ("NAME", "name", 5),
            None,
            True,
            False,
        ]

        with io.StringIO() as output:
            sh_print(*items_to_print, file=output)
            result = output.getvalue()

        with io.StringIO() as output:
            print(*items_to_print, file=output)
            expected_result = output.getvalue()

        self.assertEqual(result, expected_result)
