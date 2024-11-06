"""Test PrettyPrinter """

import unittest
from collections import namedtuple

from ak.color import ColoredText, SHText
from ak import ppobj
from ak.ppobj import PrettyPrinter
from ak.ppobj import PPTableFieldType, PPTableField, PPTable, PPEnumFieldType


#########################
# Test json-like objects PrettyPrinter

class TestPrettyPrinter(unittest.TestCase):
    """Test PrettyPrinter"""

    def _verify_format(self, text):
        # perform some common checks of the json-looing obj printing result
        plain_text = ColoredText.strip_colors(text)
        lines = [s.lstrip() for s in plain_text.split("\n")]
        for i, line in enumerate(lines):
            self.assertNotIn(
                " \n", line,
                f"trailing spaces found in line {i}:\n|{line}|\nFull text:\n"
                f"{text}")
            # not a very good tests, because these substrings may be found inside
            # string literals. But no such string literals are used in tests.
            for bad_str in ["[ ", " ]", "{ ", " }", " ,", "_Chunk"]:
                self.assertNotIn(
                    bad_str, line,
                    f"'{bad_str}' found in line {i}:\n|{line}|\nFull text:\n"
                    f"{text}")

    def test_simple_usage(self):
        """Test processing of good json-looking object"""
        pp = PrettyPrinter().get_pptext

        # check that some text produced w/o errors
        s = pp({"a": 1, "some_name": True, "c": None, "d": [42, "aa"]})

        self._verify_format(s)

        self.assertIn("some_name", s)
        self.assertIn("42", s)

        plain_text = ColoredText.strip_colors(s)
        self.assertIn('"a": 1', plain_text)

    def test_printing_notjson(self):
        """Test that PrettyPrinter can handle not-json objects."""
        pp = PrettyPrinter().get_pptext

        s = pp(42)
        self.assertIn("42", s)

        s = pp("some text")
        self.assertIn("some text", s)

        s = pp(True)
        self.assertIn("True", s)

        s = pp(None)
        self.assertIn("None", s)

    def test_complex_object(self):
        """Test printing 'complex' object where keys have different types."""
        pp = PrettyPrinter().get_pptext

        s = pp({
            "d": {1: 23, "a": 17, "c": [1, 20, 2]},
            "ddd": "aaa",
            "a": 2, "ccc": 80,
            "z": 7,
            3: None
        })

        self._verify_format(s)

        plain_text = ColoredText.strip_colors(s)
        self.assertIn('"ccc": 80', plain_text)

    def test_ppobj_long_list(self):
        """Test pretty-printing a very long list of items."""
        pp = PrettyPrinter().get_pptext
        s = pp({
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
        })

        self._verify_format(s)

        self.assertIn("zzzzzzz", s)
        self.assertIn("101", s)
        self.assertIn("301", s)

        plain_text = ColoredText.strip_colors(s)
        # test formatting of the long list values.
        # The values in the "oitems" list will be printed on several lines.
        # This test does not care how exactly all the items are splitte into lines.
        # But several first items must fit to the very first line and so should
        # be present together in the same line.
        self.assertIn('"aaaaaaa", "bbbbbbb",', plain_text)

    def test_pprint_in_joson_fmt(self):
        """Test pprinter in json mode: result string should be colored valid json.

        (well, it will be a valid json after color sequences are removed)
        """
        pp = PrettyPrinter(fmt_json=True).get_pptext

        s = pp({
            "n": None,
            "t": True,
            "f": False,
        })

        self._verify_format(s)

        self.assertIn("null", s)
        self.assertIn("true", s)
        self.assertIn("false", s)


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
    ttext = ColoredText.strip_colors(orig_ttext)

    if is_colored is not None:
        table_is_colored = ttext != orig_ttext
        if is_colored:
            testcase.assertTrue(
                table_is_colored, "table is not colored:\n{table}")
        else:
            testcase.assertFalse(
                table_is_colored, "table is colored:\n{table}")

    text_lines = ttext.split('\n')

    separator_lines_ids = [
        i
        for i, line in enumerate(text_lines)
        if all(char in ('+', '-') for char in line)]

    testcase.assertEqual(
        3, len(separator_lines_ids),
        f"table is expected to contain 3 separator lines:\n{table}")

    testcase.assertEqual(
        0, separator_lines_ids[0],
        f"first line of a table should be a separator line::\n{table}")

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
            f"unexpected column names in table:\n{table}")

    # 2. verify number of lines
    if n_body_lines is not None:
        testcase.assertEqual(
            actual_n_body_lines, n_body_lines,
            f"unexpected number of body lines in table:\n{table}")

    # 3. verify columns widths
    if cols_widths is not None:
        actual_col_widths = [len(x) for x in text_lines[0][1:-1].split('+')]
        testcase.assertEqual(
            cols_widths, actual_col_widths,
            f"unexpected column widths in table:\n{table}")

    # 4. verify contains specified text
    if contains_text is not None:
        if not isinstance(contains_text, (list, tuple)):
            contains_text = [contains_text, ]
        for t in contains_text:
            testcase.assertIn(
                t, ttext, f"table doesn't contain text '{t}':\n{table}")

    # 5. verify does not contain specified text
    if not_contains_text is not None:
        if not isinstance(not_contains_text, (list, tuple)):
            not_contains_text = [not_contains_text, ]
        for t in not_contains_text:
            testcase.assertNotIn(
                t, ttext, f"table unexpectedly contains text '{t}':\n{table}")

    # verify all lines has same length
    for i, line in enumerate(text_lines):
        testcase.assertEqual(
            table_width, len(line),
            f"length of line #{i} = {len(line)}:\n{line}\nis different from "
            f"lengths of other lines. Table\n{table}")


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
                f"looks differently:\n{ttext_0}\n{ttext_1}")

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
            title_records=[
                ('iddescr', 'll', 'nnnn'),
                (555, 777, None),
            ],
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
        dflt_field_type = PPTableFieldType()
        fields = [
            PPTableField(
                field_name,
                pos,
                dflt_field_type,
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
        class CustomFieldType(PPTableFieldType):
            """Produce some text, which is not just str(value)"""
            def make_desired_text(
                self, value, fmt_modifier, syntax_names,
            ) -> ([SHText._Chunk], int):
                """Custom format value for a table column.

                This one appends some text to a value.

                By default 'custom descr" string is appended to teh value.
                But if format modifier was specified for a table column
                this modifier wil be appended.
                """
                syntax_name = syntax_names.get("TABLE.NUMBER")
                if not fmt_modifier:
                    text_items = [SHText._Chunk(syntax_name, str(value) + " custom descr")]
                else:
                    text_items = [SHText._Chunk(syntax_name, str(value) + " " + fmt_modifier)]

                return text_items, ppobj.ALIGN_LEFT

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
            999: ("Error status", "WARN"),
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

        with self.assertRaises(ValueError) as exc:
            PPTable(records, fmt=(
                "id:10,"  # value_path is not specified
                " name<-0.2,country<-1.1"))

        err_msg = str(exc.exception)
        self.assertIn("value_paths not found", err_msg)

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

    def test_print_method(self):
        """Test PPTable.print method"""

        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
            (5, 9, "Hermiona"),
        ]

        table = PPTable(records, fields=['id', 'level', 'name'])

        table.fmt = "id,level,name;1:2"

        #print(table)
        #table.print()

        #table.print(limits=(None, None))
        #table.print()
        #table.print(no_color=True)
        #table.print()
        #self.assertTrue(False, "!!!! SUCCESS !!!!")
