"""Test PrettyPrinter """

import unittest
import io
from collections import namedtuple

from ak.color import CHText, ConfColor, ColorFmt, Palette, CompoundPalette
from ak.ppobj import CHTextResult, PrettyPrinter, pp
from ak.ppobj import (
    PPObj,
    FieldType, FieldValueType, RecordField, PPTable, PPEnumFieldType, PPRecordFmt)


#########################
# Test json-like objects PrettyPrinter

class TestPrettyPrinter(unittest.TestCase):
    """Test PrettyPrinter"""

    def _verify_format(self, text):
        # perform some common checks of the json-looing obj printing result
        plain_text = CHText.strip_colors(text)
        lines = [s.lstrip() for s in plain_text.split("\n")]
        for i, line in enumerate(lines):
            self.assertNotIn(
                " \n", line,
                f"trailing spaces found in line {i}:\n|{line}|\nFull text:\n"
                f"{text}")
            # not a very good tests, because these substrings may be found inside
            # string literals. But no such string literals are used in tests.
            for bad_str in ["[ ", " ]", "{ ", " }", " ,", "Chunk"]:
                self.assertNotIn(
                    bad_str, line,
                    f"'{bad_str}' found in line {i}:\n|{line}|\nFull text:\n"
                    f"{text}")

    def test_simple_usage(self):
        """Test processing of good json-looking object"""

        # check that some text produced w/o errors
        s = str(pp({"a": 1, "some_name": True, "c": None, "d": [42, "aa"]}))
        # print(s)

        self._verify_format(s)

        self.assertIn("some_name", s)
        self.assertIn("42", s)

        plain_text = CHText.strip_colors(s)
        self.assertIn('"a": 1', plain_text)

    def test_printing_notjson(self):
        """Test that PrettyPrinter can handle not-json objects."""

        s = str(pp(42))
        self.assertIn("42", s)

        s = str(pp("some text"))
        self.assertIn("some text", s)

        s = str(pp(True))
        self.assertIn("True", s)

        s = str(pp(None))
        self.assertIn("None", s)

    def test_complex_object(self):
        """Test printing 'complex' object where keys have different types."""

        s = str(pp({
            "d": {1: 23, "a": 17, "c": [1, 20, 2]},
            "ddd": "aaa",
            "a": 2, "ccc": 80,
            "z": 7,
            3: None
        }))
        # print(s)

        self._verify_format(s)

        plain_text = CHText.strip_colors(s)
        self.assertIn('"ccc": 80', plain_text)

    def test_ppobj_long_list(self):
        """Test pretty-printing a very long list of items."""
        s = str(pp({
            "items": [
                {
                    "name": "x1",
                    "oitems": [
                        "aaaaaaa", "bbbbbbb", "ccccccc", "ddddddd",
                        "eeeeeee", "fffffff", "ggggggg", "hhhhhhh",
                        "eeeeeee", "fffffff", "ggggggg", "hhhhhhh",
                        "eeeeeee", "fffffff", "ggggggg", "hhhhhhh",
                        "eeeeeee", "fffffff", "ggggggg", "hhhhhhh",
                        "eeeeeee", "fffffff", "ggggggg", "hhhhhhh",
                        "eeeeeee", "fffffff", "ggggggg", "hhhhhhh",
                        "iiiiiii", "jjjjjjj", "kkkkkkk", "lllllll",
                        "zzzzzzz", 101, 201, 301
                    ],
                    "status": 1,
                    "isActive": True,
                }
            ],
        }))
        # print(s)

        self._verify_format(s)

        self.assertIn("zzzzzzz", s)
        self.assertIn("101", s)
        self.assertIn("301", s)

        plain_text = CHText.strip_colors(s)
        # test formatting of the long list values.
        # The values in the "oitems" list will be printed on several lines.
        # This test does not care how exactly all the items are splitte into lines.
        # But several first items must fit to the very first line and so should
        # be present together in the same line.
        self.assertIn('"aaaaaaa", "bbbbbbb",', plain_text)

    def test_pprint_in_json_fmt(self):
        """Test pprinter in json mode: result string should be colored valid json.

        (well, it will be a valid json after color sequences are removed)
        """
        pp_custom = PrettyPrinter(fmt_json=True)

        s = str(pp_custom({
            "n": None,
            "t": True,
            "f": False,
        }))
        # print(s)

        self._verify_format(s)

        self.assertIn("null", s)
        self.assertIn("true", s)
        self.assertIn("false", s)

    def test_different_printing_methods(self):
        """Test that different printing methods produce the same result."""

        # it's important for the test that the object to print is quite big,
        # so that it's string representation consists of several lines
        obj_to_print = {
            "d": {1: 23, "a": 17, "c": [1, 20, 2]},
            "ddd": "aaa",
            "a": 2, "ccc": 80,
            "z": 7,
            3: None
        }

        ch_result = pp(obj_to_print)

        # 1. converting pp(...) result to str.
        # new-line symbol is appended because other methods append this symbol
        converted_result = str(ch_result) + "\n"
        # print(converted_result)

        with io.StringIO() as output:
            print(ch_result, file=output)
            print_result = output.getvalue()

        with io.StringIO() as output:
            for ch_line in ch_result:
                print(ch_line, file=output)
            by_line_print_result = output.getvalue()

        self.assertEqual(converted_result, print_result)
        self.assertEqual(converted_result, by_line_print_result)


class TestCHTextResult(unittest.TestCase):
    """Test behavior of CHTextResult object.

    It should be very similar to CHText.
    """
    def test_fetch_ch_text(self):
        """Test fetching CHText object from CHTextResult."""
        ch_text_result = pp({"a": None, "b": 17, "c": "d"})
        self.assertIsInstance(ch_text_result, CHTextResult)

        ch_text = ch_text_result.get_ch_text()
        self.assertIsInstance(ch_text, CHText)

        ch_text_1 = ch_text_result.get_ch_text()
        self.assertIsNot(ch_text, ch_text_1)

    def test_printing(self):
        """Test printing of CHTextResult object."""

        # small CHTextResult object, consists of one line only.
        ch_text_result = pp({"a": None, "b": 17, "c": "d"})

        # colored string '{"a": None, "b": 17, "c": "d"}' is expected
        colored_str = str(ch_text_result)

        # 1. it should be possible just to print it
        with io.StringIO() as output:
            print(ch_text_result, file=output)
            print_result = output.getvalue()
            self.assertGreater(len(print_result), 0)
            assert print_result[-1] == "\n"
            print_result = print_result[:-1]

        self.assertEqual(print_result, colored_str)

        plain_text = CHText.strip_colors(print_result)
        self.assertNotEqual(plain_text, print_result)
        self.assertIn("None", plain_text)

    def test_iterating(self):
        """It should also be possible to iterate the result line by line.

        Even though the rusult consists of a single line.
        """
        ch_text_result = pp({"a": None, "b": 17, "c": "d"})
        colored_str = str(ch_text_result)

        s = str(CHText("\n").join(l for l in ch_text_result))
        self.assertEqual(s, colored_str)

    def test_concatenation(self):
        """Test concatenation operations"""
        ch_text_result = pp({"a": None, "b": 17, "c": "d"})
        colored_str = str(ch_text_result)

        t = "text " + ch_text_result
        self.assertIsInstance(t, CHText)
        self.assertEqual(str(t)[:5], "text ")

        t = ColorFmt("GREEN")("text ") + ch_text_result
        self.assertIsInstance(t, CHText)
        self.assertEqual(t.plain_text()[:5], "text ")

        t = CHText(ColorFmt("GREEN")("text ")) + ch_text_result
        self.assertIsInstance(t, CHText)
        self.assertEqual(t.plain_text()[:5], "text ")

        t = ch_text_result + " suffix"
        self.assertIsInstance(t, CHText)
        self.assertEqual(t.plain_text()[-7:], " suffix")

        t = ch_text_result + ColorFmt("GREEN")(" suffix")
        self.assertIsInstance(t, CHText)
        self.assertEqual(t.plain_text()[-7:], " suffix")

        t = ch_text_result + CHText(ColorFmt("GREEN")(" suffix"))
        self.assertIsInstance(t, CHText)
        self.assertEqual(t.plain_text()[-7:], " suffix")

    def test_immutable(self):
        """CHTextResult behaves as immutable object."""
        ch_text_result = pp({"a": None, "b": 17, "c": "d"})

        orig_ref = ch_text_result

        ch_text_result += " some suffix"

        self.assertNotIn("some suffix", str(orig_ref))

    def test_slicing(self):
        """Test slicing"""
        ch_text_result = pp({"a": None, "b": 17, "c": "d"})

        substring = ch_text_result[1:-1]
        self.assertEqual(len(substring), len(ch_text_result) - 2)

        substring_plain_text = substring.plain_text()
        self.assertEqual(len(substring), len(substring_plain_text))

    def test_formatting(self):
        """Test string-formatting operations"""
        t = pp([1234567890])  # colored "[1234567890]"

        s1 = f"{t:10}"
        self.assertEqual(
            str(t), str(s1), "length is > 10, so 10 in f-string has no effect")

        s1 = f"{t:~<30}" # "~~~~~~~~~~~~~~~~~~[1234567890]"
        self.assertGreater(len(s1), 30, "s1 contains color sequences")

        s1_stripped = CHText.strip_colors(s1)
        self.assertEqual(len(s1_stripped), 30)

    def test_fixed_len_method(self):
        """Make sure CHTextResult.fixed_len method exists and works."""
        t = pp([1234567890])  # colored "[1234567890]"

        result = t.fixed_len(5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result.plain_text(), "[1234")

        result = t.fixed_len(15)
        self.assertEqual(len(result), 15)
        self.assertEqual(result.plain_text(), "[1234567890]   ")

    def test_equality(self):
        """Test equality checks."""
        t1 = pp({"a": None, "b": 17, "c": "d"})
        t2 = pp({"a": None, "b": 17, "c": "d"})

        self.assertEqual(t1, t1)
        self.assertEqual(t1, t2)


#########################
# Test PPObj

class TestSimplePPObj(unittest.TestCase):
    """Test simple Pretty-Printable object."""

    class SimplePPObj(PPObj):
        """Simple PPObj."""

        # PPObj should have PALETTE_CLASS:
        class MyPalette(Palette):
            SYNTAX_DEFAULTS = {
                "X.C1": "NUMBER",
                "X.C2": "BLUE",
            }
            color_1 = ConfColor("X.C1")
            color_2 = ConfColor("X.C2")

        PALETTE_CLASS = MyPalette

        def __init__(self, val1, val2):
            self.val1 = val1
            self.val2 = val2

        def make_ch_text(self, palette):
            """Method which produces color representaion of self.

            Alternatively it is possible to implement 'gen_ch_lines' method.
            """
            return palette.color_1(self.val1) + palette.color_2(self.val2)

    def test_simple_ppobj(self):
        """Test behavior of a simple PPObj."""

        # 0. create an instance of SimplePPObj
        obj = self.SimplePPObj("aa", "bb")

        # 1. It is possible to get palette, which will be used to print this object
        obj_palette = obj.make_palette()
        # print(obj_palette.make_report())

        # 2. It is possible just to print it
        with io.StringIO() as output:
            print(obj, file=output)
            print_result = output.getvalue().strip()

        expected_result = str(ColorFmt("YELLOW")("aa") + ColorFmt("BLUE")("bb"))

        self.assertEqual(print_result, expected_result)

    def test_palette_in_compound_palette(self):
        """Test how ppobj may use palette from CompoundPalette."""

        class AltSimplePPObjPalette1(self.SimplePPObj.MyPalette):
            """Alternative palette to be used by SimplePPObj."""
            SYNTAX_DEFAULTS = {
                "ALT1_C1": "RED",
                "ALT1_C2": "YELLOW",
            }
            color_1 = ConfColor("ALT1_C1")
            color_2 = ConfColor("ALT1_C2")

        class AltSimplePPObjPalette2(self.SimplePPObj.MyPalette):
            """Alternative palette to be used by SimplePPObj."""
            SYNTAX_DEFAULTS = {
                "ALT2_C1": "CYAN",
                "ALT2_C2": "MAGENTA",
            }
            color_1 = ConfColor("ALT2_C1")
            color_2 = ConfColor("ALT2_C2")

        class BigObjPalette(CompoundPalette):
            SUB_PALETTES_MAP = {
                (self.SimplePPObj.MyPalette, None): AltSimplePPObjPalette1,
                (self.SimplePPObj.MyPalette, "cm"): AltSimplePPObjPalette2,
            }

        palette = BigObjPalette()

        # now palette contains information about alternative palette for
        # the SimplePPObj.
        # It can be used to print the object

        obj = self.SimplePPObj("aaa", "bbb")

        text_std = obj.ch_text()

        # 1. compound palette is used. But it contains no alternative palette
        # for our class and shade "unexpected shade". So, standard palette is used.
        chtext = obj.ch_text(compound_palette=palette, shade_name="unexpected shade")
        self.assertEqual(chtext, text_std)

        # 2. compound palette is used. Shade is not specified.
        # AltSimplePPObjPalette1 is used in this case (see SUB_PALETTES_MAP)
        chtext = obj.ch_text(compound_palette=palette)
        self.assertNotEqual(chtext, text_std)
        self.assertEqual(
            chtext,
            ColorFmt("RED")("aaa") + ColorFmt("YELLOW")("bbb"),
        )

        # 3. compound palette is used, shade is specified.
        chtext = obj.ch_text(compound_palette=palette, shade_name="cm")
        self.assertNotEqual(chtext, text_std)
        self.assertEqual(
            chtext,
            ColorFmt("CYAN")("aaa") + ColorFmt("MAGENTA")("bbb"),
        )


#########################
# Test PPTable

def verify_table_format(
        testcase, table,
        has_header=False,
        is_colored=None,
        cols_names=None,
        n_extra_title_lines=None,
        n_body_lines=None,
        cols_widths=None,
        contains_text=None,
        not_contains_text=None,
):
    """Verify that table is printed out correctly.

    Arguments:
    - table: either PPTable object or a sring
    Printed table looks like:

    +--+-----+------+
    |some table     |
    |id|level|name  |
    +--+-----+------+
    | 1|   10|Linus |
    | 2|   10|Arnold|
    | 3|   17|Jerry |
    | 4|    7|Elizer|
    +--+-----+------+
    Total 4 records  <- including trailing spaces here
    """
    orig_ttext = table if isinstance(table, str) else str(table)
    ttext = CHText.strip_colors(orig_ttext)

    if is_colored is not None:
        table_is_colored = ttext != orig_ttext
        if is_colored:
            testcase.assertTrue(
                table_is_colored, "table is not colored:\n{orig_ttext}")
        else:
            testcase.assertFalse(
                table_is_colored, "table is colored:\n{orig_ttext}")

    text_lines = ttext.split('\n')

    separator_lines_ids = [
        i
        for i, line in enumerate(text_lines)
        if all(char in ('+', '-') for char in line)]

    testcase.assertEqual(
        3, len(separator_lines_ids),
        f"table is expected to contain 3 separator lines:\n{orig_ttext}")

    testcase.assertEqual(
        0, separator_lines_ids[0],
        f"first line of a table should be a separator line::\n{orig_ttext}")

    header_part = text_lines[separator_lines_ids[0]+1:separator_lines_ids[1]]
    col_names_line_id = 1 if has_header else 0
    testcase.assertGreater(
        len(header_part), col_names_line_id,
        f"header part of table should consist of optional table name line, "
        f"column names line, and optional additional column titles. "
        f"(for this table has_header = {has_header}")

    column_names_line = header_part[col_names_line_id]

    actual_n_body_lines = separator_lines_ids[2] - separator_lines_ids[1] - 1

    table_width = len(text_lines[0])

    # 1. verify column names
    if cols_names is not None:
        actual_col_names = []
        if len(column_names_line) > 2:
            actual_col_names = [
                x.strip() for x in column_names_line[1:-1].split('|')]
        testcase.assertEqual(
            actual_col_names, cols_names,
            f"unexpected column names in table:\n{orig_ttext}")

    # 2. verify number of lines
    if n_body_lines is not None:
        testcase.assertEqual(
            actual_n_body_lines, n_body_lines,
            f"unexpected number of body lines in table:\n{orig_ttext}")

    # 3. verify columns widths
    if cols_widths is not None:
        actual_col_widths = [len(x) for x in text_lines[0][1:-1].split('+')]
        testcase.assertEqual(
            cols_widths, actual_col_widths,
            f"unexpected column widths in table:\n{orig_ttext}")

    # 4. verify contains specified text
    if contains_text is not None:
        if not isinstance(contains_text, (list, tuple)):
            contains_text = [contains_text, ]
        for t in contains_text:
            testcase.assertIn(
                t, ttext, f"table doesn't contain text '{t}':\n{orig_ttext}")

    # 5. verify does not contain specified text
    if not_contains_text is not None:
        if not isinstance(not_contains_text, (list, tuple)):
            not_contains_text = [not_contains_text, ]
        for t in not_contains_text:
            testcase.assertNotIn(
                t, ttext, f"table unexpectedly contains text '{t}':\n{orig_ttext}")

    # verify all lines has same length
    for i, line in enumerate(text_lines):
        testcase.assertEqual(
            table_width, len(line),
            f"length of line #{i} = {len(line)}:\n{line}\nis different from "
            f"lengths of other lines. Table\n{orig_ttext}")


class TestPPTable(unittest.TestCase):
    """Test PPTable - pretty-printable table of records."""

    def test_simple_table(self):
        """Test formatting of a simple table."""
        # 0. prepare the table for experiments

        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]

        table = PPTable(records, fields=['id', 'level', 'name'])

        # 1. check how the table looks
        # print(table)
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4, # all 4 records expected to be visible
        )

        # 2. specify format explicitely
        # columns are in different order, some are duplicated
        table.fmt = "id:5,id:10,  level:11,name:15, level:20"

        ttext_0 = str(table)
        verify_table_format(
            self, table,
            cols_names=['id', 'id', 'level', 'name', 'level'],
            n_body_lines=4, # all 4 records expected to be visible
            cols_widths=[5, 10, 11, 15, 20],
        )

        # 3. specify format, which changes only numbers of visible records
        for fmt in ["", ";", ";;", ";20:20", ";20:20;"]:
            table.fmt = fmt
            ttext_1 = str(table)

            self.assertEqual(
                ttext_0, ttext_1,
                f"format string '{fmt}' was not expected to change the "
                f"table format (only number of visible records could have changed, "
                f"but it is always enough to show all records). Still table now "
                f"looks differently:\n{ttext_0}\n{ttext_1}.\n"
                f"It happened after fmt was set to '{fmt}'"
            )

        # 4. check number of records behavior
        for fmt in [";0:3", ";1:2", ";3:0"]:
            table.fmt = fmt
            ttext_1 = str(table)

            self.assertEqual(
                ttext_0, ttext_1,
                f"total number of header and footer records to show is 3. "
                f"it is less than total number of records. But it makes no "
                f"sence to skip 1 line. So, all records should be displayed, "
                f"but table looks differently:\n{ttext_0}\n{ttext_1}")

        # 5. limit number of visible records
        table.fmt = ";1:0"
        verify_table_format(
            self, table,
            cols_names=['id', 'id', 'level', 'name', 'level'],
            n_body_lines=2, # 1 line with resord + a line with number of skipped
            cols_widths=[5, 10, 11, 15, 20],
        )

        # 6. fall back to default format
        table.fmt = "*;*"
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4,
        )

        # 7. check columns with zero widths do not break anything
        for fmt in ["id:5,level:0,name:15", "id:0,level:0,name:0"]:
            table.fmt = fmt
            verify_table_format(
                self, table,
                n_body_lines=4,
            )

        # 8. check zero visible lines do not break anything
        table.fmt = "id:5, level:10, name:15 ;0:0"
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=1, # no visible records, but there is a "num skipped"
            cols_widths=[5, 10, 15],
        )

        # 9. verify column-width ranges work
        table.fmt = "id:1-2,level:1-2,name:1-2;*"
        verify_table_format(
            self, table,
            # cols_names=['id', 'level', 'name'], - not enough space to print them
            n_body_lines=4,
            cols_widths=[2, 2, 2],  # actual widths are min or max allowed
        )

        table.fmt = "id:15-20,level:15-20,name:15-20;*"
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4,
            cols_widths=[15, 15, 15],  # actual widths are min allowed
        )

        # 10. check 'fmt' is reported correctly
        table.fmt = " id:10,   level:15"  # specify some format
        table.fmt = ";;"  # set another - this fmt does not actually change anything

        cur_fmt = str(table.fmt)

        self.assertIn(
            "id:10,level:15", cur_fmt,
            f"table.fmt should contain a string, which specifies current format."
            f"In this case columns widths are fixed, so it's easy to predict "
            f"what the fmt string is")

        # 11. check format w/o widths specified
        table.fmt = "id, name, level"
        verify_table_format(
            self, table,
            cols_names=['id', 'name', 'level'],
            n_body_lines=4,
        )

        # 12. reset table to default format
        table.fmt = "*;*"
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4,
            cols_widths=[
                2,  # defined by length of name
                5,  # defined by length of name
                6,  # equal to longest value 'Arnold'
            ],
        )

    def test_remove_columns(self):
        """Test 'remove columns' functionality."""

        # 0. prepare the table for experiments
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]
        table = PPTable(
            records, fields=['id', 'level', 'name'],
            fmt="id:5,id:10,  level:11,name:15, level:20",
        )
        verify_table_format(
            self, table,
            cols_names=['id', 'id', 'level', 'name', 'level'],
            cols_widths=[5, 10, 11, 15, 20],
        )

        # 1. remove some columns by name
        table.remove_columns({'level', 'invalid_column'})
        verify_table_format(
            self, table,
            cols_names=['id', 'id', 'name'],
            cols_widths=[5, 10, 15],
        )

    def test_multi_line_titles(self):
        """Test PPTable with multi-line column titles."""
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]
        table = PPTable(
            records, fields=['id', 'level', 'name'],
            fields_titles={
                'id': ('id\niddescr', 555),
                'level': ('level\nll', 777),
                'name': ('name\nnnnn', None),
            },
            fmt="id,id:10,  level,name:1-10, level:20",
        )
        verify_table_format(
            self, table,
            cols_names=['id', 'id', 'level', 'name', 'level'],
            cols_widths=[
                7,  # len of title line 'iddescr'
                10,  # explicit value from fmt
                5,  # len of column name 'level'
                6,  # len of value 'Arnold'
                20,  # explicit value from fmt
            ],
            contains_text=['iddescr', 'll', 'nnnn', '555', '777'],
        )

    def test_lines_limits(self):
        """Check lines limits are reported correctly """
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
            (5, 9, "Hermiona"),
        ]

        table = PPTable(records, fields=['id', 'level', 'name'])

        def _get_num_vis_lines_fmt(fmt):
            # get the second section of fmt string: the one which limits
            # number of visible lines
            sections = str(fmt).split(';')
            if len(sections) > 1:
                return sections[1]
            return ""

        _ = str(table)  # simulate printing the table. Info about lines limits
                        # is initialized on printing
        self.assertEqual(
            _get_num_vis_lines_fmt(table.fmt), "",
            "all lines are visible, no need to mention lines limits in fmt")

        table.fmt = "id,level,name;1:2"
        _ = str(table)
        self.assertEqual(
            _get_num_vis_lines_fmt(table.fmt), "1:2",
            "not all lines are visible, include limits into fmt")

        # visible lines limits not specified, they remain the same
        table.fmt = "id,level,name"
        _ = str(table)
        self.assertEqual(
            _get_num_vis_lines_fmt(table.fmt), "1:2",
            "not all lines are visible, include limits into fmt")

        table.fmt = "id,level,name;1:3"
        _ = str(table)
        self.assertEqual(
            _get_num_vis_lines_fmt(table.fmt), "",
            "all lines are visible, no need to mention lines limits in fmt")

        table.fmt = "id,level,name;*"
        _ = str(table)
        self.assertEqual(
            _get_num_vis_lines_fmt(table.fmt), "",
            "all lines are visible, no need to mention lines limits in fmt")

    def test_explicit_limits(self):
        """Test explicit records limits specified in PPTable constructor."""
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
            (5, 9, "Hermiona"),
        ]

        table = PPTable(
            records, fields=['id', 'level', 'name'],
            fmt="id,level,name;1:2",
            limits=(None, None),
        )
        # default format specifies that 1+2 body lines should be printed
        # but 'limits' argument overrides these numbers and removes limits
        verify_table_format(self, table, n_body_lines=len(records))

    def test_columns_zero_width(self):
        """It's ok for a column to have 0 width.

        It does not make much sence and looks like double border, but
        it should work.
        """
        records = [
            (10, "Arnold"),
            (10, "Arnold"),
            (20, "Arnold"),
        ]

        table = PPTable(
            records, fmt="grade!:0, name", fields=['grade', 'name'])

        verify_table_format(
            self, table,
            cols_names=['', 'name'],
            n_body_lines=4,  # 3 records and a 'break by' line
            cols_widths=[0, len("Arnold")],
        )

    def test_construct_with_explicit_fields(self):
        """Test creation of PPTable with manually created fields."""
        # prepare the table for experiments
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]

        # even though each record tuple has 3 elements, our table will have only
        # 2 available fiedls
        dflt_field_type = FieldType()
        fields = [
            RecordField(
                field_name,
                dflt_field_type,
                pos,
                field_name,
            ) for pos, field_name in [
                (0, 'id'),
                (2, 'name'),
            ]
        ]

        table = PPTable(records, fields=fields)
        verify_table_format(
            self, table,
            cols_names=['id', 'name'],
            n_body_lines=4, # all 4 records expected to be visible
            cols_widths=[2, 6],
        )

    def test_construct_by_sample_record(self):
        """Test PPTable constructed by sample record."""
        # prepare the table for experiments
        RecType = namedtuple('RecType', ['id', 'level', 'name'])

        records = [
            RecType(1, 10, "Linus"),
            RecType(2, 10, "Arnold"),
            RecType(3, 17, "Jerry"),
            RecType(4, 7, "Elizer"),
        ]

        # in case records are not empty it's ok to skip 'sample' argument -
        # the first record will be used as a sample
        table = PPTable(records)
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4,  # all 4 records expected to be visible
            cols_widths=[2, 5, 6],
        )

    def test_construct_with_custom_field_types(self):
        """Test PPTable with custom field type.

        This filed type supports modifiers.
        """

        # 0. prepare custom field type
        class CustomFieldType(FieldType):
            """Produce some text, which is not just str(value)"""
            def make_desired_cell_ch_chunks(
                self, value, fmt_modifier, _c,
            ) -> ([CHText.Chunk], int):
                """Custom format value for a table column.

                This one appends some text to a value.

                By default "custom descr" string is appended to the value.
                But if format modifier was specified for a table column
                this modifier wil be appended.
                """
                if not fmt_modifier:
                    str_val = str(value) + " custom descr"
                else:
                    str_val = str(value) + " " + fmt_modifier
                text_items = [_c.number(str_val)]

                return text_items, FieldType.ALIGN_LEFT

            def is_fmt_modifier_ok(self, fmt_modifier):
                """Verify 'fmt_modifier' is acceptable by this Field Type.

                For test purposes one specific value of format modifier is
                prohibited for this field type.
                """
                if fmt_modifier == 'jInXedText':
                    return False, f"'{fmt_modifier}' is not acceptable"
                return True, ""

        custom_field_type = CustomFieldType()

        # 0.1 prepare the table
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]
        table = PPTable(
            records, fields=['id', 'level', 'name'],
            fields_types={'level': custom_field_type},
        )

        # 1. check how table looks
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4, # all 4 records expected to be visible
            cols_widths=[
                2,
                15,  # length of custom field "10 custom descr"
                6,
            ],
            contains_text="custom descr",
        )

        # 2. specify format modifier for some columns
        table.fmt = "id,level,name,level/cust_msg"
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name', 'level'],
            n_body_lines=4, # all 4 records expected to be visible
            cols_widths=[
                2,
                15,  # length of custom field "10 custom descr"
                6,
                11,  # length of custom field "10 cust_msg"
            ],
            contains_text=["custom descr", "cust_msg"],
        )

        # 3. make sure prohibited format modifier is properly rejected
        with self.assertRaises(ValueError) as exc:
            table.fmt = "id,level,name,level/jInXedText"

        err_msg = str(exc.exception)
        self.assertIn("jInXedText", err_msg)

    def test_construct_with_header(self):
        """Test PPTable with manually specified description (header)."""
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]

        table = PPTable(
            records,
            header="My Table Description",
            fields=['id', 'level', 'name'],
            fmt="id:2, level:5, name:5",  # to make sure header would not fit
        )

        verify_table_format(
            self, table,
            has_header=True,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4,  # all 4 records expected to be visible
            contains_text="My Table",  # begining of the header must be present
        )

    def test_table_with_enum_field_type(self):
        """Test table with enum field type."""

        # 0. prepare enum field type
        statuses_enum = PPEnumFieldType({
            10: "Ok status",
            999: ("Error status", "name_warn"),
        })

        # 0.1 prepare the table
        records = [
            (1, "user 01", 10),
            (2, "user 02", 999),
        ]

        table = PPTable(
            records, fields=['id', 'name', 'status'],
            fields_types={'status': statuses_enum},
        )

        # 1. chech how table looks
        verify_table_format(
            self, table,
            cols_names=['id', 'name', 'status'],
            n_body_lines = 2,
            cols_widths = [
                2, # column name 'id'
                7, # 'name 01'
                16, # '999 Error status'
            ],
            contains_text=[
                "10 Ok status",
            ]
        )

        # 2. create several columns same field different formats
        table.fmt = "id, status/name, status/full, status/val, status"
        verify_table_format(
            self, table,
            cols_names=['id', 'status', 'status', 'status', 'status'],
            n_body_lines=2,
            cols_widths=[
                2, # column name 'id'
                12, # 'Error status'
                16, # '999 Error status'
                6, # 'status'
                16, # '999 Error status'
            ],
            contains_text=[
                "10 Ok status",
            ]
        )
        fmt_str = str(table.fmt)
        # table format contains status filed with format modidfiers 'val' and 'name'
        self.assertIn('status/val', fmt_str)
        self.assertIn('status/name', fmt_str)

        # 3. make sure columns with 'val' and 'name' format modifiers display
        # only value / name of enum
        table.fmt = "id, status/name"
        verify_table_format(
            self, table,
            cols_names=['id', 'status'],
            n_body_lines = 2,
            cols_widths = [
                2, # column name 'id'
                12, # 'Error status'
            ],
            contains_text=[
                "Ok status",
                "Error status",
            ],
            not_contains_text=[
                "999",
                "10",
            ],
        )

        table.fmt = "id, status/val"
        verify_table_format(
            self, table,
            cols_names=['id', 'status'],
            n_body_lines = 2,
            cols_widths = [
                2, # column name 'id'
                6, # column name 'status'
            ],
            contains_text=[
                "999",
                "10",
            ],
            not_contains_text=[
                "Ok status",
                "Error status",
            ],
        )

        # 4. test situation when record contains unexpected enum value
        records = [
            (1, "user 01", 10),
            (2, "user 02", 999),
            (3, "user 03", 20),
        ]

        table = PPTable(
            records, fields=['id', 'name', 'status'],
            fields_types={'status': statuses_enum},
        )

        verify_table_format(
            self, table,
            cols_names=['id', 'name', 'status'],
            n_body_lines = 3,
            cols_widths = [
                2, # column name 'id'
                7, # 'name 01'
                16, # '999 Error status'
            ],
            contains_text=[
                "10 Ok status",
                "<???>",
            ]
        )

        # 5. test None values in enums
        records = [
            (1, "user 01", 10),
            (2, "user 02", None),
        ]

        table = PPTable(
            records, fields=['id', 'name', 'status'],
            fields_types={'status': statuses_enum},
        )

        verify_table_format(
            self, table,
            cols_names=['id', 'name', 'status'],
            n_body_lines = 2,
            cols_widths = [
                2, # column name 'id'
                7, # 'name 01'
                13, # ' 10 Ok status'
            ],
            contains_text=[
                "10 Ok status",
            ],
            not_contains_text=[
                "<???>",
            ],
        )

    def test_table_with_break_by_columns(self):
        """Test table with 'break_by' columns."""

        records = [
            (1, "user 01", 10),
            (2, "user 02", 10),
            (3, "user 03", 10),
            (4, "user 04", 20),
            (5, "user 05", 20),
        ]

        # create table with a 'break_by' column
        table = PPTable(
            records, fields=['id', 'name', 'status'],
            fmt="name, status!, id",  # '!' means 'break by' this column
        )

        verify_table_format(
            self, table,
            cols_names=['name', 'status', 'id'],
            n_body_lines=6,  # 5 visible records + 1 'break by' line
        )

        fmt_str = str(table.fmt)
        self.assertIn('status!', fmt_str, "'status' column is 'break_by'")

        # set format with several 'break by' columns
        table.fmt = "status!,name, id!"

        verify_table_format(
            self, table,
            cols_names=['status', 'name', 'id'],
            n_body_lines=9,  # 5 visible records + 4 'break by' lines
        )

    def test_empty_table(self):
        """Test empty table when it's impossible to detect field names."""

        records = []
        table = PPTable(
            records,
            header="empty list of something",
        )

        verify_table_format(
            self, table,
            has_header=True,
            # ugly single column name used by dummy format of empty table
            cols_names=['-                              -'],
            n_body_lines = 0,
            contains_text=[
                "empty list of something",
            ],
        )


class TestByLineTableOperations(unittest.TestCase):
    """Test how colored text is generated for table in 'line-by-line' mode."""

    def test_table_ch_lines_generation(self):
        """Make sure 'by-lines' method has the same result."""
        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]

        table = PPTable(records, fields=['id', 'level', 'name'])

        result_whole = str(table)

        result_by_lines = str(CHText("\n").join(table.ch_text()))

        self.assertEqual(result_whole, result_by_lines)

    def test_concurrent_lines_generation(self):
        """Test concurrent generation of lines of the same table."""

        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]

        table = PPTable(records, fields=['id', 'level', 'name'])

        result = str(
            CHText("\n").join(
                t0_line + t1_line
                for t0_line, t1_line in zip(table.ch_text(), table.ch_text())))

        # print(result)
        # It is expected to look like this:
        # +--+-----+------++--+-----+------+
        # |id|level|name  ||id|level|name  |
        # +--+-----+------++--+-----+------+
        # | 1|   10|Linus || 1|   10|Linus |
        # | 2|   10|Arnold|| 2|   10|Arnold|
        # | 3|   17|Jerry || 3|   17|Jerry |
        # | 4|    7|Elizer|| 4|    7|Elizer|
        # +--+-----+------++--+-----+------+
        # Total 4 records  Total 4 records  <- trailing spaces here

        result = CHText.strip_colors(result)
        self.assertIn("|id|level|name  ||id|level|name  |", result)

    def test_cuncurrent_using_different_palettes(self):
        """Test concurrent lines generation using different palettes."""

        class RedTablePalette(PPTable.TablePalette):
            border = ConfColor('TABLE.WARN')

        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]

        table = PPTable(records, fields=['id', 'level', 'name'])

        # two green tables side-by-side
        result_0 = str(
            CHText("\n").join(
                t0_line + t1_line
                for t0_line, t1_line in zip(
                    table.ch_text(palette=RedTablePalette),
                    table.ch_text(),
                )))
        # print(result_0)

        # red and green tables side-by-side
        result_1 = str(
            CHText("\n").join(
                t0_line + t1_line
                for t0_line, t1_line in zip(
                    table.ch_text(palette=RedTablePalette),
                    table.ch_text(),
                )))
        # print(result_1)

        # use palette object instead of palette class
        red_palette = RedTablePalette()
        result_2 = str(
            CHText("\n").join(
                t0_line + t1_line
                for t0_line, t1_line in zip(
                    table.ch_text(),
                    table.ch_text(palette=red_palette),
                )))
        # print(result_2)

        # not colored tables
        result_3 = str(
            CHText("\n").join(
                t0_line + t1_line
                for t0_line, t1_line in zip(
                    table.ch_text(no_color=True),
                    table.ch_text(no_color=True),
                )))
        # print(result_3)

        result_0 = CHText.strip_colors(result_0)
        result_1 = CHText.strip_colors(result_1)
        result_2 = CHText.strip_colors(result_2)

        self.assertEqual(result_1, result_0)
        self.assertEqual(result_2, result_0)
        self.assertEqual(result_3, result_0)


class TestEnhancedPPTable(unittest.TestCase):
    """Enhanced tables are used to display not 'simple' records.

    'simple' records are just lists/tuples of values.
    Not simple record may have non-trivial structure (list of disctionaries etc.)
    """

    def test_extended_table_simple_case(self):
        """Test straightforward case"""
        records = [
            # records have complex structure: info about a person and info about
            # country.
            ((1, 10, "Linus"), ('fn', 'Finland')),
            ((2, 10, "Arnold"), ('ru', 'Russia')),
            ((3, 17, "Jerry"), ('nw', 'Neverland')),
            ((4, 7, "Elizer"), ('iz', 'Izrael')),
        ]

        table = PPTable(records, fmt=(
            "id<-0.0:10, name<-0.2,country<-1.1"))
        verify_table_format(
            self, table,
            cols_names=['id', 'name', 'country'],
            n_body_lines=4,
            cols_widths=[10, len("Arnold"), len('Neverland')],
        )

    def test_records_with_namedtuples_and_dicts(self):
        """Test records containing namedtuples and dictionaries."""

        PersData = namedtuple('PersData', ['id', 'level', 'name'])

        records = [
            # records have complex structure: info about a person and info about
            # country.
            (PersData(1, 10, "Linus"), {'c_code': 'fn', 'c_name': 'Finland'}),
            (PersData(2, 10, "Arnold"), {'c_code': 'ru', 'c_name': 'Russia'}),
            (PersData(3, 17, "Jerry"), {'c_code': 'nw', 'c_name': 'Neverland'}),
            (PersData(4, 7, "Elizer"), {'c_code': 'iz', 'c_name': 'Izrael'}),
        ]

        table = PPTable(records, fmt=(
            "name<-0.name, id<-0.id,c_name<-1.[c_name],"
            "level<-0.level, c_code<-1.[c_code]"))
        verify_table_format(
            self, table,
            cols_names=['name', 'id', 'c_name', 'level', 'c_code'],
            n_body_lines=4,
            cols_widths=[
                len("Arnold"), len('id'), len('Neverland'),
                len('level'), len('c_code')])

        t0_text = str(table)

        # it is possible to omit last element of value_path if it is the same as
        # field name
        table = PPTable(records, fmt=(
            "name<-0., id<-0.,"  # 'name<-0.' is shortcut of 'name<-0.name'
            "c_name<-1.[c_name],"
            "level<-0.1, "  # 'level<-0.1' == 'level<-0.level' (it's namedtuple)
            "c_code<-1.[c_code]"))
        t1_text = str(table)
        self.assertEqual(t0_text, t1_text, "formats are equivalent")

    def test_columns_referring_same_field(self):
        """Case when several columns refer to the same field.

        Deacriptions of such column must not conflict.
        """
        records = [
            # records have complex structure: info about a person and info about
            # country.
            ((1, 10, "Linus"), ('fn', 'Finland')),
            ((2, 10, "Arnold"), ('ru', 'Russia')),
            ((3, 17, "Jerry"), ('nw', 'Neverland')),
            ((4, 7, "Elizer"), ('iz', 'Izrael')),
        ]

        table = PPTable(records, fmt=(
            "id:10,"  # value_path is not specified, but it's ok because ...
            " name<-0.2,country<-1.1,"
            "id<-0.0:20,"  # ... it is specified in this column descr
            "id<-0.0:15"  # value_path redefined, but ok - is the same
        ))
        verify_table_format(
            self, table,
            cols_names=['id', 'name', 'country', 'id', 'id'],
            n_body_lines=4,
            cols_widths=[10, len("Arnold"), len('Neverland'), 20, 15],
        )

        with self.assertRaises(ValueError) as exc:
            PPTable(records, fmt=(
                "id<-0.0,"
                "id<-0.1"  # conflicting value_path for field 'id'
            ))

        err_msg = str(exc.exception)
        self.assertIn("different value_paths for the same field", err_msg)

    def test_break_by(self):
        """'break_by' and 'value_path' are both present in the fmt.

        Make sure fmt is parsed correctly in this case.
        """
        records = [
            ((10, "Linus"), ),
            ((10, "Arnold"), ),
            ((20, "Arnold"), ),
        ]

        table = PPTable(records, fmt="seat!<-0.0:3-10,owner<-0.1")
        verify_table_format(
            self, table,
            cols_names=['seat', 'owner'],
            n_body_lines=4,  # 3 records and 1 break_by
            cols_widths=[len('seat'), len("Arnold")],
        )

    def test_invisible_columns(self):
        """Test columns with width '-1'.

        When PPTable is created using 'enhanced' format information about
        fields is incorporated into columns description. To create a field
        without a column it is possible to specify it's withd -1.
        """
        records = [
            ((10, "Linus"), ),
            ((10, "Arnold"), ),
            ((20, "Arnold"), ),
        ]

        table = PPTable(records, fmt="seat<-0.0:-1,owner<-0.1")
        #print(table)

        verify_table_format(
            self, table,
            cols_names=['owner'],
            n_body_lines=3,
            cols_widths=[len("Arnold")],
        )

        # But the field 'seat' was created and it can be used when we set new fmt
        table.fmt = "seat, owner"
        verify_table_format(
            self, table,
            cols_names=['seat', 'owner'],
            n_body_lines=3,
            cols_widths=[len('seat'), len("Arnold")],
        )


class TestCustomFieldValueType(unittest.TestCase):
    """Test FieldValueType."""

    def test_success_scenario(self):
        """Simple scenario of FieldValueType usage."""
        # 1. create the custom FieldValueType
        class CustomFieldValue(FieldValueType):
            class CustomFildPalette(FieldValueType.PALETTE_CLASS):
                """For test is is important that the Palette has it's own method"""
                SYNTAX_DEFAULTS = {
                    "RECORD.CUSTOM": "YELLOW:bold",
                }
                custom = ConfColor("RECORD.CUSTOM")

            PALETTE_CLASS = CustomFildPalette

            def __init__(self, x):
                self.x = x

            def make_desired_cell_ch_chunks(self, fmt_modifier, field_palette):
                """Creates it's representation."""
                return [
                    field_palette.text("the value is "),
                    field_palette.number(str(self.x)),
                    field_palette.custom("!"),
                ], FieldType.ALIGN_LEFT

        # 2. create a table, which displays these values

        records = [
            (1, CustomFieldValue(10)),
            (5, CustomFieldValue(20)),
        ]

        table = PPTable(records, fields=['id', 'descr'])

        # print(table)

        # 3. make sure the the desired text generated by
        # CustomFieldValue.make_desired_cell_ch_chunks is present in the table
        verify_table_format(
            self, table,
            cols_names=['id', 'descr'],
            n_body_lines=2,
            cols_widths=[len('id'), len("the value is 10!")],
            contains_text="the value is 10!",
        )


class TestPPRecordFormatter(unittest.TestCase):
    """Test PPRecordFmt class"""

    def test_simple_case(self):
        """Test PPRecordFmt usage when record is a simple tuple."""
        rec_fmt = PPRecordFmt(
            "id, name, age",
            fields=["id", "name", "age"],
        )

        r = rec_fmt((10, "John", 42))

        s = str(r)
        plain = CHText.strip_colors(s)
        self.assertNotEqual(s, plain)
        self.assertEqual(plain, "10 John 42")

        ch = r.ch_text()
        self.assertIsInstance(ch, CHText)

        # check values of individual columns
        id_ch_text = r.cols_by_name['id']
        self.assertIsInstance(id_ch_text, CHText)
        id_text = CHText.strip_colors(str(id_ch_text))
        self.assertEqual(id_text, "10")

        # check 'no_color' option
        self.assertEqual(
            str(rec_fmt((10, "John", 42), no_color=True)),
            "10 John 42")

    def test_record_fmt_named_tuple(self):
        """Test PPRecordFmt usage when record is a named tuple."""

        tupletype = namedtuple("SomeRecord", ["id", "description", "department"])
        record = tupletype(10, "short", 245)

        # 1. Standard construction: using 'fmt' string
        rec_fmt = PPRecordFmt("id:7,description:7,department:9")

        s = CHText.strip_colors(str(rec_fmt(record)))
        # Expected result: 3 fields having widths 7 7 9 separated by space:
        #                    0123456 0123456 012345678"
        self.assertEqual(s, "     10 short         245")

        # 2. Create formatter by sample record
        rec_fmt = PPRecordFmt(None, sample_record=record)

        rec_repr = rec_fmt(record)
        s = CHText.strip_colors(str(rec_repr))
        # Expected result: 3 fields separated by space:
        self.assertEqual(s, "10 short 245")

        dep_ch_text = rec_repr.cols_by_name['department']
        self.assertEqual(dep_ch_text.plain_text(), "245")
