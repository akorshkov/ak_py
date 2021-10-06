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
            ['account_id', 'name'],
        )

        @method_sql
        def get_account(self, account_id):
            """Get account by id."""
            db_conn = self.get_sql_conn()
            return self._MTD_SQL_GET_ACCOUNT.one(db_conn, account_id)

    class MethodsCollection2(MCallerSql):
        """Another collection of sql requests wrappers."""

        _MTD_SQL_GET_DOC = SqlMethod(
            "SELECT id, description FROM documents WHERE id = ?;",
            ['document_id',],
            'document',
            ['doc_id', 'descr'],
        )

        @method_sql('docs_component')
        def get_document(self, doc_id):
            """Get account by id."""
            db_conn = self.get_sql_conn()
            return self._MTD_SQL_GET_DOC.one(db_conn, doc_id)

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

    def _make_sample_db_docs(self):
        # create sample sqlite3 db for tests
        db = sqlite3.connect(":memory:")
        cur = db.cursor()
        cur.execute(
            "CREATE TABLE documents "
            "(id PRIMARY KEY, description TEXT) ")
        cur.executemany(
            "INSERT INTO documents (id, description) VALUES (?, ?)",
            [(10, "python tutorial"), (20, "c++ book")],
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
            def __init__(self, db):
                self.sql_db_addr = db

        h_text_class = h(MySqlCallerSingleConn)
        self.assertIn("get_account", h_text_class)

        my_sql_caller = MySqlCallerSingleConn(db)

        account = my_sql_caller.get_account(1).r
        self.assertEqual("MI6", account.name)
        account = my_sql_caller.get_account_r(1)
        self.assertEqual("MI6", account.name)

        h_text_obj = h(my_sql_caller)
        self.assertIn("get_account", h_text_obj)

        # 2. Check behavior of a similar class with map of connections
        class MySqlCallerMapConns(self.MethodsCollection1):
            """Methods of this class wrap sql requests."""
            def __init__(self, db):
                self.sql_dbs_addrs = {None: db}

        h_text_class = h(MySqlCallerMapConns)
        self.assertIn("get_account", h_text_class)

        my_sql_caller = MySqlCallerMapConns(db)

        account = my_sql_caller.get_account(1).r
        self.assertEqual("MI6", account.name)
        account = my_sql_caller.get_account_r(1)
        self.assertEqual("MI6", account.name)

        h_text_obj = h(my_sql_caller)
        self.assertIn("get_account", h_text_obj)

    def test_sql_caller_not_available_method(self):
        """Check sql caller with not some components not configured."""
        # create and populate database
        db_accts = self._make_sample_db_accts()
        db_docs = self._make_sample_db_docs()

        h = HCommand()._make_help_text

        class MySqlCaller(self.MethodsCollection1, self.MethodsCollection2):
            """Methods of this class wrap sql requests."""
            def __init__(self, dbs_addrs):
                self.sql_dbs_addrs = dbs_addrs

        h_text_class = h(MySqlCaller)
        self.assertIn("get_account", h_text_class)
        self.assertIn("get_document", h_text_class)

        # check behavior of caller with configured connection to accounts db only
        caller_accts = MySqlCaller({None: db_accts})

        h_text_obj = h(caller_accts)
        self.assertIn("get_account", h_text_obj)
        self.assertNotIn(
            "get_document", h_text_obj,
            "expected n/a because conn to docs db not specified")

        account = caller_accts.get_account(1).r
        self.assertEqual("MI6", account.name)

        with self.assertRaises(ValueError) as err:
            caller_accts.get_document(7)
        err_msg = str(err.exception)
        self.assertIn('docs_component', err_msg)

        # check behavior of caller with configured connection to all required dbs
        caller = MySqlCaller({None: db_accts, 'docs_component': db_docs})

        h_text_obj = h(caller)
        self.assertIn("get_account", h_text_obj)
        self.assertIn("get_document", h_text_obj)

        account = caller.get_account(1).r
        self.assertEqual("MI6", account.name)

        doc = caller.get_document(20).r
        self.assertEqual("c++ book", doc.descr)
