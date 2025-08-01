"""Test FieldType classes from the predefined collection."""

import unittest

from datetime import datetime

from ak.color import ColorFmt
from ak.ppobj import PPTable
from ak.pp_fields_types import (
    date_time_field_type, title_field_type,
    PPEnumFieldType, MatrixFieldValueType,
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
            cols_names=['Date', 'Date', 'DateT', 'DateT', 'DateT', 'Nth', 'Nth'],
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
            cols_names=['Key', 'Value'],
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
