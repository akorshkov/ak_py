"""Test MCallerSql -base class for "method callers" of sql requests."""

import unittest

import sqlite3

from ak.hdoc import HCommand
from ak.mcaller_sql import MCallerSql, SqlMethodT, method_sql
from ak.ppobj import PPTable


class TestMCallerSQL(unittest.TestCase):
    """Test functionality of MCallerSql classes.

    MCallerHttp is a MethodCaller which wraps sql requests.
    """

    class MethodsCollection1(MCallerSql):
        """Collection of sql requests wrappers."""

        _MTD_SQL_GET_ACCOUNT = SqlMethodT(
            "SELECT id, name FROM accounts WHERE id = ?;",
            ['account_id',],
            'account',
        )

        @method_sql
        def get_account(self, account_id):
            """Get account by id."""
            db_conn = self.get_sql_conn()
            return self._MTD_SQL_GET_ACCOUNT.one(db_conn, account_id)

    def _make_sample_db_accts(self):
        # create sample sqlite3 db for tests
        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            "CREATE TABLE accounts "
            "(id PRIMARY KEY, name TEXT) ")
        cur.executemany(
            "INSERT INTO accounts (id, name) VALUES (?, ?)",
            [(1, "MI6"), (2, "MathLab")],
        )
        cur.execute(
            "CREATE TABLE users "
            "(id PRIMARY KEY, account_id INT, name TEXT)")
        cur.executemany(
            "INSERT INTO users (id, account_id, name) VALUES (?, ?, ?)",
            [(10, 1, "Arnold"), (20, 1, "Linus")],
        )
        db.commit()

        return db

    def test_sql_method_no_component(self):
        """Test scenarios when component property is not used."""
        # create and populate database
        db = self._make_sample_db_accts()

        h = HCommand()._make_help_text

        # Final class can keep connection either in 'sql_db_addr' or
        # in 'sql_dbs_addrs'.
        # 1. Check behavior of class with single connection
        class MySqlCallerSingleConn(self.MethodsCollection1):
            """Methods of this class wrap sql requests."""
            pass

        h_text_class = h(MySqlCallerSingleConn)
        self.assertIn("get_account", h_text_class)

        my_sql_caller = MySqlCallerSingleConn(db)

        account = my_sql_caller.get_account(1).r[0]

        self.assertEqual("MI6", account.name)
        account = my_sql_caller.get_account(1).r[0]
        self.assertEqual("MI6", account.name)

        h_text_obj = h(my_sql_caller)
        self.assertIn("get_account", h_text_obj)

    def test_sql_select_with_joins(self):
        """Test behavior SqlMethodT with request with joins."""

        class MySqlCallerSingleConn(self.MethodsCollection1):
            """Methods of this class wrap sql requests."""
            _MTD_SQL_GET_USERS = SqlMethodT(
                "SELECT users.id AS u_id, users.name, accounts.* FROM users "
                "JOIN accounts ON users.account_id = accounts.id;",
                [],
                "users_dets",  # this is name of the table / record
            )

            @method_sql
            def get_users(self):
                """Get all users data"""
                db_conn = self.get_sql_conn()
                return self._MTD_SQL_GET_USERS.list(db_conn)

        db = self._make_sample_db_accts()
        my_sql_caller = MySqlCallerSingleConn(db)

        users = my_sql_caller.get_users()
        # repr(users)
        # print(users)

        self.assertTrue(isinstance(users, PPTable))
        self.assertEqual(4, len(users._columns), "all 4 columns are visible")
        self.assertEqual(['u_id', 'name', 'id', 'name'], users.field_names)
        self.assertEqual(2, len(users.r), "there are 2 users in the database")

    def test_sql_select_with_custom_fields(self):
        """Test behavior SqlMethodT with request with joins."""

        class MySqlCallerSingleConn(self.MethodsCollection1):
            """Methods of this class wrap sql requests."""
            _MTD_SQL_GET_USERS = SqlMethodT(
                "SELECT users.id AS u_id, users.name, accounts.* FROM users "
                "JOIN accounts ON users.account_id = accounts.id;",
                [],
                "users_dets",  # this is name of the table / record
                columns=['id', 'u_id'],
            )

            @method_sql
            def get_users(self):
                """Get all users data"""
                db_conn = self.get_sql_conn()
                return self._MTD_SQL_GET_USERS.list(db_conn)

        db = self._make_sample_db_accts()
        my_sql_caller = MySqlCallerSingleConn(db)

        users = my_sql_caller.get_users()
        # repr(users)

        self.assertTrue(isinstance(users, PPTable))
        self.assertEqual(
            2, len(users._columns), "only 'id' and 'u_id' columns are visible")
        self.assertEqual(['u_id', 'name', 'id', 'name'], users.field_names)
        self.assertEqual(2, len(users.r), "there are 2 users in the database")

    def test_ambiguous_filed_name(self):
        """Can't create SqlMethodT because of ambiguous field name."""

        # this method is 'bad', but it will only be possible to detect it
        # during the first run
        bad_method = SqlMethodT(
            "SELECT users.id AS u_id, users.name, accounts.* FROM users "
            "JOIN accounts ON users.account_id = accounts.id;",
            [],
            "users_dets",  # this is name of the table / record
            columns=['id', 'u_id', 'name'],
        )

        db = self._make_sample_db_accts()

        with self.assertRaises(AssertionError) as err:
            bad_method.list(db)

        err_msg = str(err.exception)
        self.assertIn("field name 'name' can't be used", err_msg)
