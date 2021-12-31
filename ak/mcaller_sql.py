"""Tools for creation of "methods caller" objects for sql requests."""

from ak.hdoc import BoundMethodNotes
from ak.mcaller import MCaller
from ak.mtd_sql import SqlMethod
from ak.ppobj import PPTable, PPTableFormat


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
            self, sql_request, params_names=None, record_name=None, *,
            header=None, footer=None, fmt=None, field_types=None):
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
        Format of the result table may be modified with following args:
        PPTableFormat-related arguments:
        - header, footer: optional custom header and footer of the table.
          Check doc of al.ppobj.PPTable for more details
        - fmt, field_types: optional table format specifications.
          Check ak.ppobj.PPTableFormat for more details
        """
        if isinstance(sql_request, SqlMethod):
            assert params_names is None
            assert record_name is None
            self.sql_request = sql_request
        else:
            self.sql_request = SqlMethod(sql_request, params_names, record_name)

        self.field_names = None  # list of names of attributes of selected records.
                                 # names are unique, available only after the
                                 # first request is done

        # stored arguments for PPTableFormat constructor
        self._ppt_fmt = fmt
        self._ppt_field_types = field_types
        self._ppt_format = None  # to be initialized later

        # stored arguments for result PPTables constructors
        self._record_name = None
        self._ppt_header = header
        self._ppt_footer = footer

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
        if self._ppt_format is None:
            self._finish_init()

        return PPTable(
            records,
            header=self._ppt_header,
            footer=self._ppt_footer,
            fmt_obj=self._ppt_format,
        )

    def _finish_init(self):
        # finish init self, if not done yet
        #
        # it's posible to finich init only after first request executed
        # (only then names of selected fields are available)

        self._record_name = self.sql_request.record_name
        self.field_names = self._make_unique_names_list(self.sql_request.fields)
        if self._ppt_header is None:
            # construct default header
            self._ppt_header = f"{self._record_name} table"

        self._ppt_format = PPTableFormat(
            self._ppt_fmt, fields=self.field_names,
            field_types=self._ppt_field_types)

    @staticmethod
    def _make_unique_names_list(names_list):
        # rename elements to make them unique:
        #
        # ['id', 'name', 'id', 'name'] -> ['id', 'name', 'id_1', 'name_1']

        names_set = set(names_list)
        if len(names_list) == len(names_set):
            # all names are unique already
            return names_list

        result = []
        counters = {}
        for name in names_list:
            if name in counters:
                n = counters[name] + 1
                while True:
                    fixed_name = f"{name}_{n}"
                    if fixed_name not in names_set:
                        break
                    n += 1
                counters[name] = n
                names_set.add(fixed_name)
                result.append(fixed_name)
            else:
                counters[name] = 0
                result.append(name)

        return result


class MCallerSql(MCaller):
    """Base class for "sql method callers"."""

    def __init__(self, db_conn=None, *,
                 db_connector=None, connector_args=None, connector_kwargs=None):
        """Create sql methods caller.

        Arguments:
        - db_conn: db connection object
        - db_connector, connector_args, connector_kwargs: optional values, which
        can be used to re-create db_conn.
        """
        if db_conn is not None:
            assert db_connector is None, (
                f"conflicting arguments 'db_conn' ({db_conn}) and "
                f"db_connector' ({db_connector})")
        else:
            assert db_connector is not None, (
                f"either 'db_conn' or 'db_connector' argument must be specified")

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
