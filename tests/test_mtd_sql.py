"""Test sql methods."""

import unittest
from ak.mtd_sql import SQLMethod
import sqlite3


class TestSQLMethod(unittest.TestCase):
    """Test SQLMethod class."""

    def test_sql_select_single_record(self):
        """Test sql-select method. Single record is expected to be selected."""

        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            """CREATE TABLE accounts
            (id PRIMARY KEY, name TEXT, status INT)
            """)
        cur.executemany(
            "INSERT INTO accounts (id, name, status) VALUES (?, ?, ?)",
            [(1, "MI6", 7),
             (2, "MathLab", 42),
            ])
        db.commit()

        # test method which selects one record
        account_by_id = SQLMethod(
            'account_record',
            ['id', 'name', 'status'],
            ['account_id'],
            "SELECT id, name, status FROM accounts WHERE id = ?",
        )

        # existing record: 3 ways to call the method should produce same data
        result = account_by_id.one(db, 1)
        self.assertEqual(1, result.id)
        self.assertEqual("MI6", result.name)

        results = account_by_id.all(db, 1)
        self.assertEqual(1, len(results))
        self.assertEqual(result, results[0])

        result = account_by_id.one_or_none(db, 1)
        self.assertEqual(result, results[0])

        # no record
        with self.assertRaises(ValueError) as err:
            account_by_id.one(db, 10)

        self.assertIn("not found", str(err.exception))

        results = account_by_id.all(db, 10)
        self.assertEqual([], results)

        result = account_by_id.one_or_none(db, 10)
        self.assertIsNone(result)

    def test_sql_select_multiple_records(self):
        """Test sql select when there are multiple or no records to return."""

        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            """CREATE TABLE users
            (id PRIMARY KEY, name TEXT, account_id INT)
            """)
        cur.executemany(
            "INSERT INTO users (id, name, account_id) VALUES (?, ?, ?)",
            [(1, "James", 1),
             (2, "Arnold", 1),
            ])
        db.commit()

        get_users_by_account = SQLMethod(
            'account_record',
            ['id', 'name'],
            ['account_id'],
            "SELECT id, name FROM users WHERE account_id = ?",
        )

        # test 'no records found' situation
        self.assertEqual(
            [], get_users_by_account.all(db, 5),
            "there are no users with account_id=5 in db")

        self.assertIsNone(get_users_by_account.one_or_none(db, 5))

        with self.assertRaises(ValueError):
            get_users_by_account.one(db, 5)

        # test 'multiple records found' situation
        users = get_users_by_account.all(db, 1)
        self.assertEqual(2, len(users))

        with self.assertRaises(ValueError):
            get_users_by_account.one(db, 1)

        with self.assertRaises(ValueError):
            get_users_by_account.one_or_none(db, 1)

    def test_arguments_processing(self):
        """Test test arguments and keyword arguments processing."""

        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            """CREATE TABLE accounts
            (id PRIMARY KEY, prop1 INT, prop2 INT, prop3 INT, prop4 INT)
            """)
        cur.executemany(
            "INSERT INTO accounts(id, prop1, prop2, prop3, prop4) "
            "VALUES (?, ?, ?, ?, ?)",
            [(1, 10, 20, 30, 40),
             (2, 100, 200, 300, 400),
            ])

        db.commit()

        get_accounts_ids = SQLMethod(
            'accounts',
            ['id'],  # names of values to select
            ['arg1', 'arg2', 'arg3', 'arg4'],  # names of filter arguments
            "SELECT id FROM accounts "
            "WHERE prop1 = ? AND prop2 = ? AND prop3 = ? AND prop4 = ?")

        # try different combinations of list arguments and kwargs
        account_id = get_accounts_ids.one(db, 10, 20, 30, 40).id
        self.assertEqual(1, account_id)

        account_id = get_accounts_ids.one(
            db, arg1=10, arg2=20, arg3=30, arg4=40).id
        self.assertEqual(1, account_id)

        account_id = get_accounts_ids.one(db, 10, arg3=30, arg2=20, arg4=40).id
        self.assertEqual(1, account_id)

        # and try different incorrect arguments combinations
        with self.assertRaises(ValueError) as err:
            get_accounts_ids.one(db, 10, 20, 30)
        self.assertIn("invalid number of arguments specified", str(err.exception))

        with self.assertRaises(ValueError) as err:
            get_accounts_ids.one(db, 10, 20, 30, 40, 50)
        self.assertIn("invalid number of arguments specified", str(err.exception))

        with self.assertRaises(ValueError) as err:
            get_accounts_ids.one(db, 20, 30, arg1=10, arg4=40)

        with self.assertRaises(ValueError) as err:
            get_accounts_ids.one(db, 10, 20, 30, argx=40)

        with self.assertRaises(ValueError) as err:
            get_accounts_ids.one(db, 10, 20, 30, 40, argx=40)
