"""Test MCallerSql -base class for "method callers" of sql requests."""

import unittest

import sqlite3

from ak.hdoc import HCommand
from ak.mtd_sql import SqlMethod
from ak.mcaller_sql import MCallerSql, method_sql


class TestMCallerSQL(unittest.TestCase):
    """Test functionality of MCallerSql classes.

    MCallerHttp is a MethodCaller which wraps sql requests.
    """

    class MethodsCollection1(MCallerSql):
        """Collection of sql requests wrappers."""

        _MTD_SQL_GET_ACCOUNT = SqlMethod(
            "SELECT id, name FROM accounts WHERE id = ?;",
            ['account_id',],
            'accounts',
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

        account = my_sql_caller.get_account(1).r
        self.assertEqual("MI6", account.name)
        account = my_sql_caller.get_account_r(1)
        self.assertEqual("MI6", account.name)

        h_text_obj = h(my_sql_caller)
        self.assertIn("get_account", h_text_obj)
