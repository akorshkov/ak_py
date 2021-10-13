"""Tools for creation of "methods caller" objects for sql requests."""

from ak.hdoc import BoundMethodNotes
from ak.mcaller import MCaller


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
