"""Test sql methods."""

import unittest
from collections import namedtuple
import sqlite3

from ak.mtd_sql import SqlMethod

# import logging
# logging.basicConfig(level=logging.DEBUG)


class TestSQLMethod(unittest.TestCase):
    """Test SqlMethod class."""

    def _make_sample_db_accounts(self, records=None):
        # create and populate sample sqlite db to use in tests
        if records is None:
            records = [
                (1, "MI6", 7),
                (2, "MathLab", 42),
            ]

        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            """CREATE TABLE accounts
            (id PRIMARY KEY, name TEXT, status INT)
            """)
        cur.executemany(
            "INSERT INTO accounts (id, name, status) VALUES (?, ?, ?)",
            records,
            )
        db.commit()

        return db

    def _make_sample_db_users(self, records=None):
        # create and populate sample sqlite db to use in tests
        if records is None:
            records = [
                (1, "James", 1),
                (2, "Arnold", 1),
            ]

        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            """CREATE TABLE users
            (id PRIMARY KEY, name TEXT, account_id INT)
            """)
        cur.executemany(
            "INSERT INTO users (id, name, account_id) VALUES (?, ?, ?)",
            records,
            )
        db.commit()

        return db

    def test_sql_select_single_record(self):
        """Test sql-select method. Single record is expected to be selected."""

        db = self._make_sample_db_accounts()

        # test method which selects one record
        account_by_id = SqlMethod(
            "SELECT id, name, status FROM accounts",
            record_name='account_record',
        )

        # existing record: 3 ways to call the method should produce same data
        result = account_by_id.one(db, id=1)
        self.assertEqual(
            ['id', 'name', 'status'], account_by_id.fields,
            ".fileds should contain actual fields names after first call")
        self.assertEqual(1, result.id)
        self.assertEqual("MI6", result.name)

        results = account_by_id.list(db, id=1)
        self.assertEqual(1, len(results))
        self.assertEqual(result, results[0])

        result = account_by_id.one_or_none(db, id=1)
        self.assertEqual(result, results[0])

        # no record
        with self.assertRaises(ValueError) as err:
            account_by_id.one(db, id=10)

        self.assertIn("not found", str(err.exception))

        results = account_by_id.list(db, id=10)
        self.assertEqual([], results)

        result = account_by_id.one_or_none(db, id=10)
        self.assertIsNone(result)

    def test_sql_select_multiple_records(self):
        """Test sql select when there are multiple or no records to return."""

        db = self._make_sample_db_users()

        get_users_by_account = SqlMethod(
            "SELECT id, name FROM users",
            record_name='account_record',
        )

        # test 'no records found' situation
        self.assertEqual(
            [], get_users_by_account.list(db, account_id=5),
            "there are no users with account_id=5 in db")

        self.assertIsNone(get_users_by_account.one_or_none(db, account_id=5))

        with self.assertRaises(ValueError):
            get_users_by_account.one(db, account_id=5)

        # test 'multiple records found' situation
        users = get_users_by_account.list(db, account_id=1)
        self.assertEqual(2, len(users))

        with self.assertRaises(ValueError):
            get_users_by_account.one(db, account_id=1)

        with self.assertRaises(ValueError):
            get_users_by_account.one_or_none(db, account_id=1)

    def test_as_scalar_option(self):
        """Test SqlMethod as_scalars option."""
        db = self._make_sample_db_users()

        # 1. check method, which returns records by default
        get_users = SqlMethod(
            "SELECT id, name, account_id FROM users",
            record_name='user',
        )

        # 1.1 with method's default as_scalars=False
        users = get_users.list(db)
        self.assertEqual(2, len(users))
        users_by_id = {u.id: u for u in users}
        self.assertEqual("Arnold", users_by_id[2].name)

        # 1.2 with _as_scalars=True option
        users_ids = get_users.list(db, _as_scalars=True)
        self.assertEqual({1, 2}, set(users_ids))

        arnold_id = get_users.one(db, _as_scalars=True, name="Arnold")
        self.assertEqual(2, arnold_id)

        # 2. check method, which returns scalars by default
        get_users = SqlMethod(
            "SELECT id, name, account_id FROM users",
            record_name='user',
            as_scalars=True,
        )

        # 2.1 with method's default as_scalars=True
        users_ids = get_users.list(db)
        self.assertEqual({1, 2}, set(users_ids))

        arnold_id = get_users.one(db, name="Arnold")
        self.assertEqual(2, arnold_id)

        # 2.2 with _as_scalars=False option
        users = get_users.list(db, _as_scalars=False)
        self.assertEqual(2, len(users))
        users_by_id = {u.id: u for u in users}
        self.assertEqual("Arnold", users_by_id[2].name)

    def test_arguments_processing(self):
        """Test test arguments and keyword arguments processing."""

        db = self._make_sample_db_users()

        get_users_ids = SqlMethod(
            "SELECT id FROM users ",
            record_name='user',
            as_scalars=True,
        )

        james_id = 1
        arnold_id = 2

        # try different combinations of list arguments and kwargs
        # 1. no filter conditions
        recs_ids = get_users_ids.list(db)
        self.assertEqual({1, 2}, set(recs_ids))

        # 2. still no filter conditions ('_order_by' is not a filter condition!)
        recs_ids = get_users_ids.list(db, _order_by="account_id, name DESC")
        self.assertEqual([1, 2], recs_ids)
        recs_ids = get_users_ids.list(db, _order_by="name")
        self.assertEqual([2, 1], recs_ids)

        # 3. filter format, which can be used in very simple cases
        self.assertEqual(james_id, get_users_ids.one(db, name="James"))

        # 4. filer in (name, value) format
        self.assertEqual(james_id, get_users_ids.one(db, ('name', "James")))

        # 5. filer in (name, op, value) format
        self.assertEqual(james_id, get_users_ids.one(db, ('name', '=', "James")))

        # 6. filer 'not equal'
        self.assertEqual(arnold_id, get_users_ids.one(db, ('name', '!=', "James")))

        # 7. 'IN' filter
        self.assertEqual(james_id, get_users_ids.one(db, ('name', 'IN', ["James"])))

        # 8. 'NOT IN' filter
        self.assertEqual(
            arnold_id, get_users_ids.one(db, ('name', 'NOT IN', ["James"])))

        # 9. filter 'IN' empty
        self.assertIsNone(get_users_ids.one_or_none(db, ('name', 'IN', [])))

        # 10. filter 'NOT IN' empty
        self.assertEqual({1, 2}, set(get_users_ids.list(db, ('name', 'NOT IN', []))))

        # 11. 'LIKE' filter
        self.assertEqual(james_id, get_users_ids.one(db, ('name', 'LIKE', "%am%")))

        # 12. 'NOT LIKE' filter
        self.assertEqual(
            arnold_id, get_users_ids.one(db, ('name', 'NOT LIKE', "%am%")))

        # 13. 'static' filter condition
        self.assertEqual(james_id, get_users_ids.one(db, "id = account_id"))
        self.assertEqual(
            james_id, get_users_ids.one(db, "id = account_id", account_id=1))
        self.assertEqual(arnold_id, get_users_ids.one(db, "id != account_id"))

        # to test 'IS NULL' and 'IS NOT NULL' let's create one more record
        cur = db.cursor()
        cur.executemany(
            "INSERT INTO users (id, name, account_id) VALUES (?, ?, ?)",
            [(3, "Harry", None)])
        db.commit()
        harry_id = 3
        recs_ids = get_users_ids.list(db, _order_by="id")
        self.assertEqual([1, 2, 3], recs_ids)

        # 14. filter 'IS NULL'
        self.assertEqual(
            harry_id, get_users_ids.one(db, ('account_id', 'IS NULL', None)))
        self.assertEqual(harry_id, get_users_ids.one(db, ('account_id', '=', None)))
        self.assertEqual(harry_id, get_users_ids.one(db, account_id=None))

        # 15. filter 'IS NOT NULL'
        recs_ids = get_users_ids.list(db, ('account_id', 'IS NOT NULL', None))
        self.assertEqual({1, 2}, set(recs_ids))
        recs_ids = get_users_ids.list(db, ('account_id', '!=', None))
        self.assertEqual({1, 2}, set(recs_ids))

        # 16. dummy filter (does not filter anything)
        self.assertEqual(
            james_id, get_users_ids.one(db, None, ('name', '=', "James")))
        self.assertEqual(james_id, get_users_ids.one(db, None, name="James"))

    def test_complex_conditions(self):
        """Test SqlMethod._or condition."""

        db = self._make_sample_db_users(
            [
                (1, "James", 1),
                (2, "Arnold", 1),
                (3, "Chuck", 7),
                (4, "Harry", 7),
                (5, "Asimov", 7),
            ])

        get_users_ids = SqlMethod(
            "SELECT id FROM users ",
            record_name='user',
            as_scalars=True,
        )

        # 0. verify db state
        recs_ids = get_users_ids.list(db)
        self.assertEqual({1, 2, 3, 4, 5}, set(recs_ids))

        # 1. single simple 'or' condition
        recs_ids = get_users_ids.list(db, SqlMethod._or(id=2, name="Chuck"))
        self.assertEqual({2, 3}, set(recs_ids))

        recs_ids = get_users_ids.list(db, SqlMethod._or())
        self.assertEqual(
            set(), set(recs_ids), "zero operands combined with 'OR' is FALSE")

        recs_ids = get_users_ids.list(db, SqlMethod._or(name="Chuck"))
        self.assertEqual({3}, set(recs_ids))

        # 2. a little more complex condition
        recs_ids = get_users_ids.list(
            db, SqlMethod._or(name="Chuck", id=2), account_id=1)
        self.assertEqual(
            {2}, set(recs_ids),
            "Condition is identical to 'account_id = 1 AND (name='Chuck' OR id=2'")

    def test_aggregation(self):
        """Test requests with 'GROUP BY' clause."""

        db = self._make_sample_db_users(
            [
                (1, "James", 1),
                (2, "Arnold", 1),
                (3, "Chuck", 7),
                (4, "Harry", 7),
                (5, "Asimov", 7),
            ])

        mtd = SqlMethod(
            "SELECT SUM(id) AS sid, account_id FROM users",
            group_by='account_id',
        )

        # 1. do the test call
        # expected result: [
        #   (sid=3, account_id=1),
        #   (sid=8, account_id=7),
        # ]
        recs = mtd.list(
            db, ('name', '!=', 'Harry'),
            _order_by='sid',
        )

        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0].sid, 3, f"{recs[0]}")
        self.assertEqual(recs[0].account_id, 1, f"{recs[0]}")
        self.assertEqual(recs[1].sid, 8, f"{recs[1]}")
        self.assertEqual(recs[1].account_id, 7, f"{recs[1]}")


class TestRecordsMMap(unittest.TestCase):
    """Test SqlMethod.records_mmap method.

    This is a helper which classifies records by specified attributes:
    records -> {key1: {key2: ... {keyN: record}...}}
    """

    def test_rrecord_map_maker(self):
        """Test normal successful scenario."""
        ttype = namedtuple('document', ['vault_id', 'doc_id', 'name', 'size'])
        records = [
            ttype(10, 1, 'secret doc 10 1', 17),
            ttype(20, 1, 'secret doc 20 1', 17),
            ttype(10, 3, 'secret doc 10 3', 42),
            ttype(10, 4, 'secret doc 10 1', 17),
        ]

        # analyze the result mmap default behavior (unique=True)
        recs_map = SqlMethod.records_mmap(records, 'vault_id', 'doc_id')
        self.assertEqual({
            10: {
                1: records[0],
                3: records[2],
                4: records[3],
            },
            20: {
                1: records[1],
            }
        }, recs_map)

        # analyze the result mmap default behavior (unique=True)
        recs_map = SqlMethod.records_mmap(records, 'vault_id', 'doc_id', unique=False)
        self.assertEqual({
            10: {
                1: [records[0], ],
                3: [records[2], ],
                4: [records[3], ],
            },
            20: {
                1: [records[1], ],
            }
        }, recs_map)

        # try sort out by not unique key
        with self.assertRaises(AssertionError) as err:
            SqlMethod.records_mmap(records, 'doc_id')

        self.assertIn("duplicate records", str(err.exception))

        # sort out by not unique key (with explicit unique=False argument)
        recs_map = SqlMethod.records_mmap(records, 'doc_id', unique=False)

        self.assertEqual(recs_map.keys(), {1, 3, 4})
        self.assertEqual(2, len(recs_map[1]))
        self.assertEqual(1, len(recs_map[3]))
        self.assertEqual(1, len(recs_map[4]))
