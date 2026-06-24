"""Test FieldType classes from the predefined collection."""

import unittest

from datetime import datetime

from ak.color import ColorFmt
from ak.ppobj import FieldType, PPTable, RecordWithConnotations
from ak.pp_fields_types import (
    date_time_field_type, title_field_type,
    PPDecimalFieldType, PPEnumFieldType, MatrixFieldValueType,
)
from .test_ppobj import verify_table_format


class TestPPTitleFieldType(unittest.TestCase):
    """Test FieldType which formats values as for columns titles."""

    def test_kv_table(self):
        """Simle success scenario."""

        # common scenario for this FieldType usage is "key-value" table.
        # The "key" column contains names of some entities and we may want to
        # format these names the same way as columns titles
        records = [
            ("Name", "Harry"),
            ("Age", 11),
        ]

        table = PPTable(
            records, fields=["key", "value"],
            fields_types={
                "key": title_field_type,
            },
        )
        # print(table)

        # Need to make sure that the values in the first column are printed
        # in the same color as column title.
        # The color is defined in _DefaultTitleFieldType.TitlePalette class.
        # Probably should make it more convenient, not sure
        s = str(ColorFmt("GREEN", bold=True)("Age"))
        self.assertIn(s, str(table))


class TestPPDateTimeFieldType(unittest.TestCase):
    """Test FieldType for datetime objects """

    def test_table_with_datetime_column(self):

        date_value = datetime(2025, 8, 1)
        dt_value = datetime(2025, 8, 1, 14, 44, 38)

        table = PPTable(
            [(date_value, dt_value, None,)],
            fields=["Date", "DateT", "Nth"],
            fmt="Date,Date/S,DateT,DateT/S,DateT/MS,Nth,Nth/S",
            fields_types={
                'Date': date_time_field_type,
                'DateT': date_time_field_type,
                'Nth': date_time_field_type,
            },
        )

        # print(table)
        verify_table_format(
            self, table,
            cols_titles=['Date', 'Date', 'DateT', 'DateT', 'DateT', 'Nth', 'Nth'],
            cols_widths=[
                #         123456789 123456789 123456
                # Date without time part
                10,    # "2025-08-01"                 default 'DT' format
                19,    # "2025-08-01 00:00:00"        'S' format
                # Date with time part
                26,    # "2025-08-01 14:44:38.000000" default 'DT' format
                19,    # "2025-08-01 14:44:38"
                26,    # "2025-08-01 14:44:38.000000"
                4,     # "None"
                4,     # "None"
            ]
        )

    def test_datetime_field_with_connotations(self):
        """Test datetime field with connotations."""

        date_value = datetime(2025, 8, 1)
        table = PPTable(
            [
                RecordWithConnotations(
                    ("some", date_value),
                    None,
                    {"date": "conn_note"},
                ),
            ],
            fields=["descr", "date"],
            fmt="descr,date",
            fields_types={
                'date': date_time_field_type,
            },
        )

        # print(table)
        t = str(table)
        self.assertIn(
            str(ColorFmt(None, underline=("DBL", "GREEN"))("2025-08-01")),
            t,
            # "conn_note" connotation adds double green underline
        )


class TestPPDecimalFieldType(unittest.TestCase):
    """Test TestPPDecimalFieldType."""

    def test_pp_decimal_field_type(self):
        """Test TestPPDecimalFieldType."""

        records = [
            ("No Value", None),
            ("Norm Dec", 1234.56),
            ("Overflow", 1234.567),
            ("Int", 1234),
        ]

        table = PPTable(
            records,
            fmt="Name<-0,V1<-1,P0<-1,Grp<-1,P3<-1,Owf<-1",
            fields_types={
                "V1": PPDecimalFieldType(),
                "P0": PPDecimalFieldType(0),
                "Grp": PPDecimalFieldType(grouping=True),
                "P3": PPDecimalFieldType(3),
                "Owf": PPDecimalFieldType(extra_digits_as_err=True),
            },
        )

        verify_table_format(
            self, table,
            cols_titles=["Name", "V1", "P0", "Grp", "P3", "Owf"]
        )

        color_text = str(table)
        plain_text = table.ch_text().plain_text()

        table_lines = plain_text.split("\n")
        titles_line = table_lines[1]
        body_lines = table_lines[3:-2]

        titles = [c.strip() for c in titles_line.split('|')[1:-1]]
        cells_values = [
            [c.strip() for c in line.split('|')[1:-1]]
            for line in body_lines]

        cells = {
            cells_line[0]: {
                title: cell
                for (title, cell) in zip(titles, cells_line)
                if title != "Name"
            } for cells_line in cells_values
        }

        values_titles = ["V1", "P0", "Grp", "P3", "Owf"]

        # check line with 'None' values.
        rd = cells["No Value"]
        for t in values_titles:
            self.assertEqual(
                rd[t], "None",
                f"Column {t}: None value should be printed as 'None':\n{color_text}")

        # check line with 'Norm Dec' values
        rd = cells["Norm Dec"]
        self.assertEqual(rd["V1"], "1234.56", f"Column V1:\n{color_text}")
        self.assertEqual(rd["P0"], "1235", f"Column P0, round to 0:\n{color_text}")
        self.assertEqual(rd["Grp"], "1,234.56", f"Column Grp:\n{color_text}")
        self.assertEqual(rd["P3"], "1234.560", f"Column P3:\n{color_text}")
        self.assertEqual(rd["Owf"], "1234.56", f"Column Owf:\n{color_text}")

        # check line with 'Owerflow' values
        rd = cells["Overflow"]
        self.assertEqual(
            rd["V1"], "1234.57",
            f"Column V1, 1234.567 round(2) -> 1234.57:\n{color_text}")
        self.assertEqual(
            rd["P0"], "1235",
            f"Column P0, 1234.567 round(0) -> 1235:\n{color_text}")
        self.assertEqual(rd["Grp"], "1,234.57", f"Column Grp:\n{color_text}")
        self.assertEqual(rd["P3"], "1234.567", f"Column P3:\n{color_text}")
        self.assertEqual(
            rd["Owf"], "1234.567",
            f"Column Owf, Value 1234.567 has :\n{color_text}")

        # check line with 'Int' values
        rd = cells["Int"]
        self.assertEqual(rd["V1"], "1234.00", f"Column V1:\n{color_text}")
        self.assertEqual(rd["P0"], "1234", f"Column P0, round to 0:\n{color_text}")
        self.assertEqual(rd["Grp"], "1,234.00", f"Column Grp:\n{color_text}")
        self.assertEqual(rd["P3"], "1234.000", f"Column P3:\n{color_text}")
        self.assertEqual(rd["Owf"], "1234.00", f"Column Owf:\n{color_text}")

        # make sure overflowed value is properly highlighted
        default_palette = FieldType._mk_palette(None, None, None, None)
        fmt = default_palette.get_color('number', 'conn_err')
        expected_text = str(fmt("1234.567")) # formatted as number and underlined
        self.assertIn(
            expected_text, color_text,
            f"Value at line 'Overflow' column 'Ovf' should be formatted as error because "
            f"the precision is not sufficient to print all digits:"
            f"\n Value:{expected_text}\n{color_text}")


class TestPPEnumFieldType(unittest.TestCase):
    """Test FieldType for enum-looking values."""

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
            cols_titles=['id', 'name', 'status'],
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
            cols_titles=['id', 'status', 'status', 'status', 'status'],
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
            cols_titles=['id', 'status'],
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
            cols_titles=['id', 'status'],
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
            cols_titles=['id', 'name', 'status'],
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
            cols_titles=['id', 'name', 'status'],
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

    def test_enum_field_type_with_connotations(self):
        """Test behavior of the enum field type when used with connotations."""

        # 0. prepare enum field type
        statuses_enum = PPEnumFieldType({
            10: "Ok status",
            999: ("Error status", "error"), # "error" here is a ConfColor name in EnumPalette
        })

        records = [
            (1, "user 01", 10),
            (2, "user 02", 999),
        ]

        table = PPTable(
            (
                RecordWithConnotations(
                    r, None,
                    {'status': 'conn_note'}
                )
                for r in records
            ),
            fields=['id', 'name', 'status'],
            fields_types={'status': statuses_enum},
        )

        s = str(table)
        # print(s)
        # "conn_note" connotation has been added to the "Status" column. This connotations
        # adds green double underline
        self.assertIn(
            str(ColorFmt("YELLOW", underline=("DBL", "GREEN"))("10")),
            s,
        )
        self.assertIn(
            str(ColorFmt(None, underline=("DBL", "GREEN"))("Ok status")),
            s,
        )
        self.assertIn(
            str(ColorFmt("YELLOW", underline=("DBL", "GREEN"))("999")),
            s,
        )
        self.assertIn(
            str(ColorFmt("RED", bold=True, underline=("DBL", "GREEN"))("Error status")),
            s,
        )


class TestMatrixFieldType(unittest.TestCase):
    """Test MatrixFieldValueType"""

    def test_matrix_table(self):
        """Test a table with a column having values of different types."""

        records = [
            ("Name", "Harry"),
            ("Age", 11),
            ("Login Date",
                MatrixFieldValueType(
                    datetime(2025, 8, 1, 17, 41, 27),
                    date_time_field_type,
                )),
            ("Next",
                MatrixFieldValueType(
                    datetime(2025, 8, 2),
                    date_time_field_type,
                    'Dt',
                )),
        ]

        table = PPTable(
            records, fields=["Key", "Value"],
            fields_types={
                "Key": title_field_type,
            }
        )

        # print(table)
        verify_table_format(
            self, table,
            cols_titles=['Key', 'Value'],
            cols_widths=[
                #         123456789 123456789 123456
                10,    # "Login Date"
                26,    # "2025-08-01 17:41:27.000000"
            ],
            contains_text=[
                # "Login Date" contains time part
                "2025-08-01 17:41:27.000000",
                # "Next" value is a date, time part skipped
                "2025-08-02                ",
            ],
        )

    def test_field_custom_palette(self):
        """Test situation when child FieldType uses own palette."""

        records = [
            ("Name Date", MatrixFieldValueType("Karl", title_field_type)),
        ]

        # The value "Karl" is supposed to be printed the same color as the columns
        # titles. The field type corresponding to the second column is standard.
        # But the value of this cell contains both the value itself (string "Karl")
        # and the field type to be used to format the value.
        table = PPTable(
            records,
            fields=["Key", "Value"],
        )

        verify_table_format(
            self, table,
            cols_titles=['Key', 'Value'],
        )

        # print(table)
