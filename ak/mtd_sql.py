"""Methods for executing predefined sql requests.

It's quite primitive - it is NOT desined to dynamically create complex sql
requests. It's a simple wrapper for manually prepared sql requests.
"""

from collections import namedtuple
import logging


logger = logging.getLogger(__name__)


class SqlMethod:
    """Python wrapper of sql request."""

    __slots__ = (
        'record_namedtuple',
        'params_names',
        'sql_request',
    )

    def __init__(self, sql_request, params_names, record_name, col_titles=None):
        """Create SqlMethod object.

        Arguments:
        - sql_request: the sql request string
        - params_names: names of sql request parameters. These names can be
            used later, when calling the method. Does not have to match
            db columns names.
        - record_name: either a namedtuple class, or a name of a new namedtuple
            class to create.
        - col_titles: should be specified if 'record_name' argument is not
            a name for a new namedtuple. In this case 'col_titles' should be
            a list of field names.
        """
        if col_titles is None:
            assert isinstance(record_name, type)
            self.record_namedtuple = record_name
        else:
            self.record_namedtuple = namedtuple(record_name, col_titles)
        self.params_names = params_names
        self.sql_request = sql_request

    @classmethod
    def make(cls, record_namedtuple, filter_columns):
        """Helper constructor.

        Arguments:
        - record_namedtuple: namedtuple type, which corresponds to a single
            database table
        - filter_columns: names of columns to filter records by
        """
        table_name = record_namedtuple.__name__
        column_names = record_namedtuple._fields
        for col in filter_columns:
            assert col in column_names, (
                f"filter column '{col}' is not present in list of all "
                f"columns {column_names}")
        sql_string = (
            "SELECT " + ", ".join(n for n in column_names) + " FROM " + table_name)
        if filter_columns:
            sql_string += " WHERE " + " AND ".join(f"{n} = ?" for n in filter_columns)

        return cls(sql_string, filter_columns, record_namedtuple)

    def _execute(self, conn, args, kwargs):
        # Execute sql request, yield result records

        # prepare list of arguments for request
        if len(self.params_names) != len(args) + len(kwargs):
            raise ValueError(
                f"invalid number of arguments specified. "
                f"Expected {self.params_names} ({len(self.params_names)} args), "
                f"actually received {args} + {kwargs} "
                f"({len(args)} + {len(kwargs)} = {len(args)+len(kwargs)} args)"
            )
        req_params = list(args)
        for arg_id in range(len(args), len(self.params_names)):
            arg_name = self.params_names[arg_id]
            if arg_name not in kwargs:
                raise ValueError(
                    f"missing argument #{arg_id} ('{arg_name}'). "
                    f"Expected args: {self.params_names}. "
                    f"Actual args: {args} + {kwargs}"
                )
            req_params.append(kwargs[arg_name])

        # and execute request
        cur = conn.cursor()
        logger.debug("SQL request: %s ; params: %s", self.sql_request, req_params)
        cur.execute(self.sql_request, req_params)  # some databases return data here,
                                                   # others - number of affected records.
        for raw in cur:
            yield self.record_namedtuple._make(raw)

    def all(self, conn, *args, **kwargs):
        """Execute sql request, yield result records."""
        yield from self._execute(conn, args, kwargs)

    def list(self, conn, *args, **kwargs):
        """Execute sql request, return list of result records."""
        return list(self._execute(conn, args, kwargs))

    def one(self, conn, *args, **kwargs):
        """Execute sql request, return single record.

        Raise ValueError if not exactly one record was selected.
        """
        record = self.one_or_none(conn, *args, **kwargs)
        if record is None:
            raise ValueError("record not found")
        return record

    def one_or_none(self, conn, *args, **kwargs):
        """Execute sql request, return single record or None.

        Raise ValueError if more than one record was selected.
        """
        all_records = list(self._execute(conn, args, kwargs))
        if len(all_records) > 1:
            raise ValueError(f"{len(all_records)} records selected")

        return all_records[0] if all_records else None
