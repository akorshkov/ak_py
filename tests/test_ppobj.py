"""Test PrettyPrinter """

import unittest

from ak.color import ColoredText
from ak.ppobj import PrettyPrinter
from ak.ppobj import PPTableFieldType, PPTableField, PPTable

#########################
# Test json-like objects PrettyPrinter


class TestPrettyPrinter(unittest.TestCase):
    """Test PrettyPrinter"""

    def test_simple_usage(self):
        """Test processing of good json-looking object"""
        pp = PrettyPrinter().get_pptext

        # check that some text produced w/o errors
        s = pp({"a": 1, "some_name": True, "c": None, "d": [42, "aa"]})

        self.assertIn("some_name", s)
        self.assertIn("42", s)

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
        self.assertIn("ccc", s)


#########################
# Test PPTable

def verify_table_format(
        testcase, table,
        cols_names=None,
        n_body_lines=None,
        cols_widths=None):
    """Verify that table is printed out correctly.

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
    ttext = ColoredText.strip_colors(str(table))

    n_service_lines = 6  # number of lines which contain delimiters, totals etc.

    text_lines = ttext.split('\n')
    testcase.assertTrue(
        len(text_lines) >= n_service_lines,
        f"Table text should contain at least {n_service_lines} "
        f"lines with service info. Actual table:\n{table}")

    table_width = len(text_lines[0])

    # 1. verify column names
    if cols_names is not None:
        testcase.assertTrue(
            len(text_lines) > 2,
            f"line with column names is not available:\n{table}")
        actual_col_names = []
        if len(text_lines[2]) > 2:
            actual_col_names = [
                x.strip() for x in text_lines[2][1:-1].split('|')]
        testcase.assertEqual(
            actual_col_names, cols_names,
            f"unexpected column names in table:\n{table}")

    # 2. verify number of lines
    if n_body_lines is not None:
        testcase.assertEqual(
            n_body_lines, len(text_lines) - n_service_lines,
            f"unexpected number of body lines in table:\n{table}")

    # 3. verify columns widths
    if cols_widths is not None:
        actual_col_widths = [len(x) for x in text_lines[0][1:-1].split('+')]
        testcase.assertEqual(
            cols_widths, actual_col_widths,
            f"unexpected column widths in table:\n{table}")

    # verify all lines has same length
    for i, line in enumerate(text_lines):
        testcase.assertEqual(
            table_width, len(line),
            f"length of line #{i} {len(line)}:\n{line}\nis different from "
            f"lengths of other lines. Table\n{table}")


class TestPPTable(unittest.TestCase):
    """Test PPTable - pretty-printable table of records."""

    def test_simple_table(self):
        """Test formatting of a simple table."""
        # 0. prepare the table for experiments
        dflt_field_type = PPTableFieldType()

        records = [
            (1, 10, "Linus"),
            (2, 10, "Arnold"),
            (3, 17, "Jerry"),
            (4, 7, "Elizer"),
        ]
        fields = [
            PPTableField(
                field_name,
                pos,
                dflt_field_type,
            ) for pos, field_name in enumerate(['id', 'level', 'name'])
        ]

        table = PPTable(records, fmt_obj=fields)

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

        # 8. check zero visible lines does not break anything
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
