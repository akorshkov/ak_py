"""Test xlsread - helpers to read info from excel files."""

import unittest
from ak.xlsread import (
    cell_str, cell_int, cell_list, cell_bool,
    XlsObject, read_table, read_table_make_map, CellRangeSet, CellRangeDict,
    TableReader,
)
from .mock_openpyxl import MockedWorkBook, Cell


class TestXlsTables(unittest.TestCase):

    def test_mock_cells_coordinate(self):
        """test cells coordinate calculation algorithm."""
        self.assertEqual("A1", Cell.make_coordinate(0, 0))
        self.assertEqual("A2", Cell.make_coordinate(1, 0))
        self.assertEqual("B100", Cell.make_coordinate(99, 1))

        self.assertEqual("Z1", Cell.make_coordinate(0, 26 - 1))
        self.assertEqual("AA1", Cell.make_coordinate(0, 27 -1))
        self.assertEqual("ZZ1", Cell.make_coordinate(0, 26 + 26*26 - 1))
        self.assertEqual("AAA1", Cell.make_coordinate(0, 26 + 26*26))

    def test_mock_workbook(self):
        """Test MockedWorkBook."""
        # prepare test workbook
        wb = MockedWorkBook([
            ('sheet some data', [
                #   A     B       C    D
                '|     |10     | -1  |    |',  # line 1
                '|name |"name" |"10" |""  |',  # line 2
                "|lady |'Vashj'|'80' | '' |",  # line 2
            ]),
        ])

        # test the workbook
        ws = wb['sheet some data']
        rows = [r for r in ws.iter_rows()]

        expected_values = [
            [None, 10, -1, None],
            ["name", "name", "10", ""],
            ["lady", "Vashj", "80", ""],
        ]

        self.assertEqual(len(expected_values), len(rows))
        for line, (exp_vals, row) in enumerate(zip(expected_values, rows)):
            self.assertEqual(len(exp_vals), len(row),)
            for col, (val, cell) in enumerate(zip(exp_vals, row)):
                exp_coordinate = Cell.make_coordinate(line, col)
                self.assertEqual(exp_coordinate, cell.coordinate)
                self.assertEqual(val, cell.value, f"cell {cell}")

    def test_parsing_simple_table(self):
        """Read data from a very simple table."""
        class XlPerson(XlsObject):
            _ATTRS = ['id', 'name', 'status']
            _NUM_ID_ATTRS = 1

        wb = MockedWorkBook([
            ('sheet1', [
                "|Id    |Person's name  |Status |",
                "|10    |Richard        |20     |",
                "|20    |Arnold         |20     |",
                "|30    |Harry          |20     |",
            ]),
        ])

        people = read_table(wb['sheet1'], XlPerson, {
            'id': ('Id', cell_int),
            'name': ("Person's name", cell_str),
            'status': ('Status', cell_int),
        })

        self.assertEqual(3, len(people), f"people: {people}")

        arnold = people[1]
        self.assertEqual(20, arnold.id)
        self.assertEqual("Arnold", arnold.name)
        self.assertEqual(20, arnold.status)

        # cehck values origins
        self.assertEqual("A3", arnold.get_attr_origin('id'))
        self.assertEqual("B3", arnold.get_attr_origin('name'))
        self.assertEqual("C3", arnold.get_attr_origin('status'))

        self.assertEqual("sheet1 A3", arnold.get_attr_origin('id', incl_ws=True))

        with self.assertRaises(ValueError) as exc:
            arnold.get_attr_origin('not_an_attr')

        err_msg = str(exc.exception)
        self.assertIn("not_an_attr", err_msg)
        self.assertIn("unknown attribute", err_msg)

        # it does not make sense to specify 'value' argument when fetching
        # origin of usual (not 'ranged') attribute.
        with self.assertRaises(ValueError) as exc:
            arnold.get_attr_origin('status', 'some_val')

        err_msg = str(exc.exception)
        self.assertIn("'status' is not a ranged attribute", err_msg)

    def test_table_reader_mixin(self):
        """Similar to test_parsing_simple_table, but rules declared in class"""

        class XlPerson(XlsObject, TableReader):
            _ATTRS = ['id', 'name', 'status']
            _NUM_ID_ATTRS = 1

            # configuration required by TableReader mixin
            ATTR_RULES = {
                'id': ('Id', cell_int),
                'name': ("Person's name", cell_str),
                'status': ('Status', cell_int),
            }

        wb = MockedWorkBook([
            ('sheet1', [
                "|Id    |Person's name  |Status |",
                "|10    |Richard        |20     |",
                "|20    |Arnold         |20     |",
                "|30    |Harry          |20     |",
            ]),
        ])

        # read_list - method implemented in TableReader
        people = XlPerson.read_list(wb['sheet1'])
        self.assertEqual(3, len(people))

        arnold = people[1]
        self.assertEqual(20, arnold.id)
        self.assertEqual("Arnold", arnold.name)
        self.assertEqual(20, arnold.status)

        # read_map - method implemented in TableReader
        people_map = XlPerson.read_map(wb['sheet1'])
        self.assertTrue(isinstance(people_map, dict))
        self.assertEqual({10, 20, 30}, people_map.keys())

        arnold = people_map[20]
        self.assertEqual(20, arnold.id)
        self.assertEqual("Arnold", arnold.name)
        self.assertEqual(20, arnold.status)

    def test_skip_columns(self):
        """It is possble to skip some attributes when reading data from table."""
        class XlPerson(XlsObject):
            _ATTRS = ['id', 'name', 'status']
            _NUM_ID_ATTRS = 1

        wb = MockedWorkBook([
            ('sheet1', [
                "|Id    |Person's name  |Status |",
                "|10    |Richard        |20     |",
                "|20    |Arnold         |20     |",
                "|30    |Harry          |20     |",
            ]),
        ])

        people = read_table(wb['sheet1'], XlPerson, {
            'id': ('Id', cell_int),
            'name': None,  # this attribute will not be read from table
            'status': ('Status', cell_int),
        })

        self.assertEqual(3, len(people), f"people: {people}")

        arnold = people[1]
        self.assertEqual(20, arnold.id)
        self.assertIsNone(arnold.name)
        self.assertEqual(20, arnold.status)

        self.assertEqual("<skipped column>", arnold.get_attr_origin('name'))

    def test_worksheet_with_empty_lines(self):
        """worksheet may start with empty lines. And columns."""
        class XlPerson(XlsObject):
            _ATTRS = ['id', 'name', 'status']
            _NUM_ID_ATTRS = 1

        wb = MockedWorkBook([
            ('sheet1', [
                "|   ||   |               |       |    |",
                "|   ||   |'    '         |       |    |",
                "|   ||Id |Person's name  |Status |    |",
                "|' '||10 |Richard        |20     |123 |",
                "|   ||20 |Arnold         |20     |    |",
                "|   ||30 |Harry          |20     |    |",
            ]),
        ])

        people = read_table(wb['sheet1'], XlPerson, {
            'id': ('Id', cell_int),
            'name': ("Person's name", cell_str),
            'status': ('Status', cell_int),
        })

        self.assertEqual(3, len(people), f"people: {people}")

        arnold = people[1]
        self.assertEqual(20, arnold.id)
        self.assertEqual("Arnold", arnold.name)
        self.assertEqual(20, arnold.status)

    def test_celllist(self):
        """Test CellList - cells which contain lists of values."""
        class XlObj(XlsObject):
            _ATTRS = ['id', 'classes']
            _NUM_ID_ATTRS = 1

        wb = MockedWorkBook([
            ('sheet1', [
                "|ID| Classes                        |",
                "|0 |math\n science,history           |",
                "|1 | computer science , \n databases |",
            ]),
        ])

        objs = read_table(wb['sheet1'], XlObj, {
            'id': ('ID', cell_int),
            'classes': ('Classes', cell_list),
        })

        self.assertEqual(2, len(objs))
        self.assertEqual(['math', 'science', 'history'], objs[0].classes)
        self.assertEqual(['computer science', 'databases'], objs[1].classes)

    def test_range_set(self):
        """Test reading XlsObject with a CellRangeSet attribute."""
        class XlObj(XlsObject):
            _ATTRS = ['id', 'name', 'classes', 'status']

        wb = MockedWorkBook([
            ('sheet1', [
                '|id | math| science|history|cs| name | status|',
                '|0  | 1   | v      |0      |  |Arnold|10     |',
                '|1  |     |        |       |  |Henry |10     |',
            ]),
        ])

        classes_set = CellRangeSet(cell_bool)

        objs = read_table(wb['sheet1'], XlObj, {
            'id': ('id', cell_int),
            'name': ('name', cell_str),
            'status': ('status', cell_int),
            'classes': ('*', classes_set),
        })

        self.assertEqual(2, len(objs))
        arnold = objs[0]
        self.assertEqual(0, arnold.id)
        self.assertEqual('Arnold', arnold.name)
        self.assertEqual(10, arnold.status)
        self.assertTrue(not hasattr(arnold, 'math'))
        self.assertEqual({'math', 'science'}, arnold.classes)

        henry = objs[1]
        self.assertEqual(set(), henry.classes)

        # check origin of the ranged attribute
        self.assertEqual("B2:E2", arnold.get_attr_origin('classes'))
        self.assertEqual(
            "sheet1 B2:E2", arnold.get_attr_origin('classes', incl_ws=True))
        self.assertEqual("B2", arnold.get_attr_origin('classes', 'math'))
        self.assertEqual(
            "sheet1 B2", arnold.get_attr_origin('classes', 'math', incl_ws=True))
        self.assertEqual("D2", arnold.get_attr_origin('classes', 'history'))
        self.assertEqual("E2", arnold.get_attr_origin('classes', 'cs'))

        self.assertEqual(
            "n/a", arnold.get_attr_origin('classes', 'philosophy', strict=False))

        with self.assertRaises(ValueError) as exc:
            arnold.get_attr_origin('classes', 'philosophy')

        err_msg = str(exc.exception)
        self.assertIn(
            "ranged attribute 'classes' has no key 'philosophy'", err_msg)

        # columns corresponding to range values may be the first in table
        wb = MockedWorkBook([
            ('sheet1', [
                '| | math| science|history|cs|id | name | status|',
                '| | 1   | v      |0      |  |0  |Arnold|10     |',
                '| |     |        |       |  |1  |Henry |10     |',
            ]),
        ])

        objs = read_table(wb['sheet1'], XlObj, {
            'id': ('id', cell_int),
            'name': ('name', cell_str),
            'status': ('status', cell_int),
            'classes': ('*', classes_set),
        })

        self.assertEqual(2, len(objs))

        arnold = objs[0]
        self.assertEqual({'math', 'science'}, arnold.classes)

        henry = objs[1]
        self.assertEqual(set(), henry.classes)

    def test_range_dict(self):
        """Test reading XlsObject with a CellRangeDict attribute."""
        class XlObj(XlsObject):
            _ATTRS = ['id', 'name', 'grades', 'status']

        wb = MockedWorkBook([
            ('sheet1', [
                '|id | math| science|history|cs| name | status|',
                '|0  | 1   | 10     |0      |  |Arnold|10     |',
                '|1  |     |        |       |  |Henry |10     |',
            ]),
        ])

        grades_reader = CellRangeDict(cell_int)

        objs = read_table(wb['sheet1'], XlObj, {
            'id': ('id', cell_int),
            'name': ('name', cell_str),
            'status': ('status', cell_int),
            'grades': ('*', grades_reader),
        })

        self.assertEqual(2, len(objs))
        arnold = objs[0]
        self.assertEqual(0, arnold.id)
        self.assertEqual('Arnold', arnold.name)
        self.assertEqual(10, arnold.status)
        self.assertTrue(not hasattr(arnold, 'math'))
        self.assertEqual({
            'math': 1,
            'science': 10,
            'history': 0,
            'cs': None,
        }, arnold.grades)

        henry = objs[1]
        self.assertEqual({
            'math': None,
            'science': None,
            'history': None,
            'cs': None,
        }, henry.grades)

    def test_xls_objects_functionality(self):
        """Test utility methods of XlsObject. """
        class XlPerson(XlsObject):
            _ATTRS = ['id', 'name', 'status']
            _NUM_ID_ATTRS = 1

        wb = MockedWorkBook([
            ('sheet1', [
                "|Id    |Person's name  |Status |",
                "|10    |Richard        |20     |",
                "|10    |Richard        |20     |",
                "|10    |Richard Diff   |20     |",
                "|20    |Arnold         |20     |",
                "|30    |Harry          |20     |",
            ]),
        ])

        people = read_table(wb['sheet1'], XlPerson, {
            'id': ('Id', cell_int),
            'name': ("Person's name", cell_str),
            'status': ('Status', cell_int),
        })

        self.assertEqual(5, len(people), f"people: {people}")

        # it's not possible to create a dictionary of people
        # because "Richard" and "Richard Diff" have same key value,
        # but different other attributes
        with self.assertRaises(ValueError) as exc:
            XlPerson.make_objects_map(people)

        err_msg = str(exc.exception)
        self.assertIn("same logic_id value 10", err_msg)
        self.assertIn("different values of attribute 'name'", err_msg)

        # let's remove 'problem' element
        # it should be possibel to create the dictionary now
        people.pop(2)

        people_by_id = XlPerson.make_objects_map(people)
        self.assertEqual(
            3, len(people_by_id), "4 people records, 2 of them are identical")
        richard = people_by_id[10]
        self.assertEqual("Richard", richard.name)
        harry = people_by_id[30]
        self.assertEqual("Harry", harry.name)

    def test_optional_columns(self):
        """Test optional columns when reading XlsObject from excel table"""
        class XlPerson(XlsObject):
            _ATTRS = ['id', 'name', 'status']
            _NUM_ID_ATTRS = 1

        wb = MockedWorkBook([
            ('sheet1', [
                "|Id    |Person's name  |",
                "|10    |Richard        |",
                "|20    |Arnold         |",
                "|30    |Harry          |",
            ]),
        ])

        with self.assertRaises(ValueError) as exc:
            read_table(wb['sheet1'], XlPerson, {
                'id': ('Id', cell_int),
                'name': ("Person's name", cell_str),
                'status': ('Status', cell_int),
            })

        err_msg = str(exc.exception)

        self.assertIn(
            "column Status required for attribute status is not found", err_msg)

        # but with explicitely specified 'optional' property it should work
        #
        # need to specify this option for column 'Status' as it is not present
        # specifying this option for a present column ('Id') should have no effect
        people = read_table(wb['sheet1'], XlPerson, {
            'id': ('Id', cell_int, {'column_is_optional': True}),
            'name': ("Person's name", cell_str),
            'status': ('Status', cell_int, {'column_is_optional': True}),
        })
        self.assertEqual(3, len(people), f"people: {people}")

        arnold = people[1]
        self.assertEqual(20, arnold.id)
        self.assertEqual("Arnold", arnold.name)
        self.assertEqual(None, arnold.status)

    def test_optional_ranged_columns(self):
        """Test corner case of a ranged attribute - zero columns correspond to it."""

        class XlObj(XlsObject):
            _ATTRS = ['id', 'name', 'classes', 'status']

        wb = MockedWorkBook([
            ('sheet1', [
                '|id | name | status|',
                '|0  |Arnold|10     |',
                '|1  |Henry |10     |',
            ]),
        ])

        classes_set = CellRangeSet(cell_bool)

        with self.assertRaises(ValueError) as exc:
            read_table(wb['sheet1'], XlObj, {
                'id': ('id', cell_int),
                'name': ('name', cell_str),
                'status': ('status', cell_int),
                'classes': ('*', classes_set),
            })

        err_msg = str(exc.exception)
        self.assertIn(
            "no columns corresponding to ranged attribute 'classes'", err_msg)

        objs = read_table(wb['sheet1'], XlObj, {
            'id': ('id', cell_int),
            'name': ('name', cell_str),
            'status': ('status', cell_int),
            'classes': ('*', classes_set, {'column_is_optional': True}),
        })

        arnold = objs[0]
        self.assertEqual(set([]), arnold.classes)

        self.assertEqual("<skipped column>", arnold.get_attr_origin('classes'))

    def test_ladder_table(self):
        """Test parsing 'ladder' table."""
        class XlEvent(XlsObject):
            _ATTRS = ['id', 'name', 'year', 'month', 'day']
            _NUM_ID_ATTRS = 1

            def get_vals(self):
                """to test assigned values."""
                return self.year, self.month, self.day

            def get_origins(self):
                """to test origins of assigned values."""
                return tuple(
                    self.get_attr_origin(attr) for attr in ['year', 'month', 'day'])

        wb = MockedWorkBook([
            ('sheet1', [
                "|' '|Year  |Month| Day | Event Id | Event name |",
                "|   |2019  |11   |30   | 1        | event 10   |",
                "|   |      |12   |15   | 2        | event 20   |",
                "|   |2020  |     |1    | 3        | event 30   |",
                "|xx |      |1    |1    | 4        | event 40   |",
                "|   |2021  |1    |1    | 5        | event 50   |",
                "|   |      |     |     | 6        | event 60   |",
                "|   |      |2    |4    | 7        | event 70   |",
            ]),
        ])

        objs = read_table_make_map(wb['sheet1'], XlEvent, {
            'id': ("Event Id", cell_int),
            'name': ("Event name", cell_str),
            'year': ("Year", cell_int),
            'month': ("Month", cell_int),
            'day': ("Day", cell_int),
        }, ladder_format=True)

        self.assertEqual(7, len(objs))

        # obj 1
        self.assertEqual((2019, 11, 30), objs[1].get_vals())
        self.assertEqual(('B2', 'C2', 'D2'), objs[1].get_origins())

        # obj 2
        self.assertEqual(
            (2019, 12, 15), objs[2].get_vals(),
            "because the table is 'ladder' value should be taken from upper call")
        self.assertIn("E3", str(objs[2]), "E3 is cooranate of 'id' cell")
        self.assertEqual("B2", objs[2].get_attr_origin('year'))
        self.assertEqual(('B2', 'C3', 'D3'), objs[2].get_origins())

        # obj 3
        self.assertEqual((2020, None, 1), objs[3].get_vals())
        self.assertEqual(('B4', 'C4', 'D4'), objs[3].get_origins())

        # obj 4
        # not empty A5 cell should not affect anything as it is outside of table
        self.assertEqual((2020, 1, 1), objs[4].get_vals())
        self.assertEqual(('B4', 'C5', 'D5'), objs[4].get_origins())

        # obj 5
        self.assertEqual((2021, 1, 1), objs[5].get_vals())
        self.assertEqual(('B6', 'C6', 'D6'), objs[5].get_origins())

        # obj 6
        self.assertEqual((2021, 1, 1), objs[6].get_vals())
        self.assertEqual(('B6', 'C6', 'D6'), objs[6].get_origins())

        # obj 7
        self.assertEqual((2021, 2, 4), objs[7].get_vals())
        self.assertEqual(('B6', 'C8', 'D8'), objs[7].get_origins())
