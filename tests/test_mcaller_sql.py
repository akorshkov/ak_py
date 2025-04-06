"""Test MCallerSql -base class for "method callers" of sql requests."""

import unittest

import sqlite3

from ak.hdoc import HCommand
from ak.mcaller_sql import MCallerSql, SqlMethodT, method_sql
from ak import ppobj
from ak.ppobj import FieldType, PPTable

from .test_ppobj import verify_table_format


class TestMCallerSQL(unittest.TestCase):
    """Test functionality of MCallerSql classes.

    MCallerHttp is a MethodCaller which wraps sql requests.
    """

    class MethodsCollection1(MCallerSql):
        """Collection of sql requests wrappers."""

        _MTD_SQL_GET_ACCOUNT = SqlMethodT(
            "SELECT id, name FROM accounts",
            record_name='account',
        )

        @method_sql
        def get_account(self, account_id):
            """Get account by id."""
            db_conn = self.get_sql_conn()
            return self._MTD_SQL_GET_ACCOUNT.one(db_conn, id=account_id)

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

        account = my_sql_caller.get_account(1).records[0]

        self.assertEqual("MI6", account.name)
        account = my_sql_caller.get_account(1).records[0]
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
                record_name="users_dets",
            )

            @method_sql
            def get_users(self):
                """Get all users data"""
                db_conn = self.get_sql_conn()
                return self._MTD_SQL_GET_USERS.list(db_conn)

        db = self._make_sample_db_accts()
        my_sql_caller = MySqlCallerSingleConn(db)

        users = my_sql_caller.get_users()

        _ = str(users)  # make sure pretty repr is generated w/o errors

        verify_table_format(
            self, users,
            has_header=True,
            n_body_lines=2,
            cols_names=['u_id', 'name', 'id', 'name_1'],
            contains_text=[
                "users_dets",  # record name should be present in default header
            ]
        )

    def test_sql_select_with_custom_format(self):
        """Test behavior SqlMethodT with not-default format."""

        # 0. prepare custom field type
        class CustomFieldType(FieldType):
            """Produce some text, which is not just str(value)"""
            def make_desired_cell_ch_text(
                self, value, fmt_modifier, _c,
            ) -> ([str|tuple], int):
                """adds some text to a value """
                text = [_c.number(str(value) + " custom descr")]
                return text, ppobj.ALIGN_LEFT

        custom_field_type = CustomFieldType()

        # 0.1 prepare the method caller
        class MySqlCallerSingleConn(self.MethodsCollection1):
            """Methods of this class wrap sql requests."""
            _MTD_SQL_GET_USERS = SqlMethodT(
                "SELECT users.id AS u_id, users.name, accounts.* FROM users "
                "JOIN accounts ON users.account_id = accounts.id;",
                record_name="users_dets",
                header="CustHeader",
                # footer="Cust footer", - not implemented
                fmt="u_id, id:10, name_1:15;*",
                fields_types={'u_id': custom_field_type},
            )

            @method_sql
            def get_users(self):
                """Get all users data"""
                db_conn = self.get_sql_conn()
                return self._MTD_SQL_GET_USERS.list(db_conn)

        db = self._make_sample_db_accts()
        my_sql_caller = MySqlCallerSingleConn(db)

        users = my_sql_caller.get_users()

        # print(users)
        # make sure that fmt specified in _MTD_SQL_GET_USERS constructor was
        # applied to the result table: only columns specified in fmt are printed
        verify_table_format(
            self, users,
            has_header=True,
            n_body_lines=2,
            cols_names=['u_id', 'id', 'name_1'],
            contains_text=[
                "CustHeader",  # explicitely specified custom header
                " custom descr",  # text added by custom_field_type to visible
                                  # column 'u_id'
            ]
        )

    def test_arbitrary_sql_call(self):
        """MCallerSql should can execute arbitary 'manual' sql requests."""
        # create and populate database
        db = self._make_sample_db_accts()

        # this MCallerSql does not wrap any methods, but can execute arbitrary
        # sql requests and return results as a PPTable
        sql_caller = MCallerSql(db)

        t = sql_caller(
            "SELECT users.id AS u_id, users.name, accounts.* FROM users "
            "JOIN accounts ON users.account_id = accounts.id;")

        self.assertTrue(isinstance(t, PPTable))

        verify_table_format(
            self, t,
            n_body_lines=2,
            cols_names=['u_id', 'name', 'id', 'name_1'],
        )
