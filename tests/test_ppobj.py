"""Test PrettyPrinter """

import unittest
from collections import namedtuple

from ak.color import ColoredText
from ak.ppobj import PrettyPrinter
from ak.ppobj import PPTableFieldType, PPTableField, PPTable, PPEnumFieldType

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
        cols_widths=None,
        contains_text=None,
        not_contains_text=None,
):
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
    testcase.assertIn(
        len(header_part), (1, 2),
        "header part of table should consist of optional header line "
        "and column names line")
    column_names_line = header_part[-1]

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
            f"length of line #{i} {len(line)}:\n{line}\nis different from "
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

        table = PPTable(records, sample=records[0])
        verify_table_format(
            self, table,
            cols_names=['id', 'level', 'name'],
            n_body_lines=4, # all 4 records expected to be visible
            cols_widths=[2, 5, 6],
        )

        # in case records are not empty it's ok to skip 'sample' argument -
        # the first record will be used as a sample
        table1 = PPTable(records)
        self.assertEqual(str(table), str(table1))

    def test_construct_with_custom_field_types(self):
        """Test PPTable with custom field types.

        This filed type supports modifiers.
        """

        # 0. prepare custom field type
        class CustomFieldType(PPTableFieldType):
            """Produce some text, which is not just str(value)"""
            def make_desired_text(self, value, fmt_modifier, palette):
                """Custom format value for a table column.

                This one appends some text to a value.

                By default 'custom descr" string is appended to teh value.
                But if format modifier was specified for a table column
                this modifier wil be appended.
                """
                fmt = palette.get_color("NUMBER")
                if not fmt_modifier:
                    text = fmt(str(value) + " custom descr")
                else:
                    text = fmt(str(value) + " " + fmt_modifier)

                return text, True  # align_left

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
            field_types={'level': custom_field_type},
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
            field_types={'status': statuses_enum},
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
            n_body_lines = 2,
            cols_widths = [
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
            field_types={'status': statuses_enum},
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
            field_types={'status': statuses_enum},
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

    def test_empty_table(self):
        """Test empty table when it's impossible to detect field names."""

        records = []
        table = PPTable(
            records,
            header="empty list of something",
        )

        verify_table_format(
            self, table,
            # ugly single column name used by dummy format of empty table
            cols_names=['-                              -'],
            n_body_lines = 0,
            contains_text=[
                "empty list of something",
            ],
        )
