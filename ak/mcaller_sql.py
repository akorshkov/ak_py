"""Tools for creation of "methods caller" objects for sql requests."""

from ak.hdoc import BoundMethodNotes
from ak.mcaller import MCaller
from ak.mtd_sql import SqlMethod
from ak.ppobj import PPTable


class MCallerMetaSqlMethod:
    """Properties of MethodsCaller method which wraps sql request.

    Created by 'method_sql' decorator.
    """
    # name of the method, which will prepare BoundMethodNotes for
    # methods decorated with this decorator
    _MAKE_BM_NOTES_METHOD = '_make_bm_notes_sql'

    def __init__(self, component):
        _ = component


def method_sql(component=None):
    """decorator to mark method as a 'wrapper' around sql request.

    Arguments:
    - component: deprecatied. Name of component which owns the database.
    """

    if callable(component):
        # decorator was used w/o parameters. The argument is actually a
        # method to decorate
        method = component
        dec = method_sql()
        return dec(method)

    def decorator(method):
        method._mcaller_meta = MCallerMetaSqlMethod(component)
        return method

    return decorator


class SqlMethodT:
    """SqlMethod which returns PPrintable PPTable object."""

    def __init__(
            self, sql_request, params_names=None, record_name=None, columns=None):
        """Create SqlMethodT - sql method which returns pretty-printable PPTable.

        SqlMethodT executes SqlMethod and presents results as PPTable.
        has two groups of arguments: SqlMethod-related and PPTable-format-related.

        SqlMethod-related arguments:
        - sql_request: either SqlMethod or a simple SQL string.
        - params_names: argument for SqlMethod constructor, can be specified
          only if sql_request is not SqlMethod. Check doc of SqlMethod constructor.
        - record_name: argument for SqlMethod constructor, can be specified
          only if sql_request is not SqlMethod. Check doc of SqlMethod constructor.

        By default result table has all the columns corresponding to sql records.
        PPTable-format-related arguments:
        - columns: list of visible columns. Each element is ither string field_name
          or integer field_pos, or a tuple of
          - filed_name_or_pos (string or int)
          - max_width  (optional)
          - min_windth  (optional)

        Note, that there may be duplicates in field names, those field names
        can't be used in 'columns' arguments.
        """
        if isinstance(sql_request, SqlMethod):
            assert params_names is None
            assert record_name is None
            self.sql_request = sql_request
        else:
            self.sql_request = SqlMethod(sql_request, params_names, record_name)

        self.name = None
        self.field_names = None

        self._columns_init = columns
        self._columns_map = None  # visible column number -> record field

    def list(self, conn, *args, **kwargs):
        """Execute sql request, return PPTable with results."""
        records = self.sql_request.list(conn, *args, **kwargs)
        return self._mk_datatable(records)

    def one_or_none(self, conn, *args, **kwargs):
        """Execute sql request, return single record or None.

        Raise ValueError if more than one record was selected.
        """
        records = self.sql_request.list(conn, *args, **kwargs)
        if len(records) > 1:
            raise ValueError(f"{len(records)} records selected")
        return self._mk_datatable(records)

    def one(self, conn, *args, **kwargs):
        """Execute sql request, return single record or None.

        Raise ValueError if more than one record was selected.
        """
        records = self.sql_request.list(conn, *args, **kwargs)
        if len(records) != 1:
            raise ValueError(f"{len(records)} records selected")
        return self._mk_datatable(records)

    def _mk_datatable(self, records):
        # records -> PPTable
        self._finish_init()
        return PPTable(self.name, self.field_names, records, self._columns_init)

    def _finish_init(self):
        # finish init self, if not done yet
        #
        # it's posible to finich init only after first request executed
        # (only then names of selected fields are available)
        if self.field_names is not None:
            return

        self.name = self.sql_request.record_name
        self.field_names = self.sql_request.fields


class MCallerSql(MCaller):
    """Base class for "sql method callers"."""
    def __init__(self, db_conn,
                 db_connector=None, connector_args=None, connector_kwargs=None):
        """Create sql methods caller.

        Arguments:
        - db_conn: db connection object
        - db_connector, connector_args, connector_kwargs: optional values, which
        can be used to re-create db_conn.
        """
        if db_connector is None:
            assert connector_args is None and connector_kwargs is None
        else:
            if connector_args is None:
                connector_args = []
            if connector_kwargs is None:
                connector_kwargs = {}

        self.db_conn = db_conn
        self.db_connector = db_connector
        self.connector_args = connector_args
        self.connector_kwargs = connector_kwargs
        if self.db_conn is None:
            self.reconnect()

    def reconnect(self):
        """Reconnect to database"""
        assert self.db_connector is not None
        self.db_conn = self.db_connector(
            *self.connector_args, **self.connector_kwargs)

    def get_sql_conn(self):
        """Returns sql connection to be used in current sql wrapper method."""
        return self.db_conn

    def _make_bm_notes_sql(self, bound_method, palette) -> BoundMethodNotes:
        # create BoundMethodNotes for bound sql-request method (method
        # decorated with 'method_sql')
        assert hasattr(bound_method, '_mcaller_meta')

        return BoundMethodNotes(True, "", None)
