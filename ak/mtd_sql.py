"""Methods for executing predefined sql requests.

It's quite primitive - it is NOT desined to dynamically create complex sql
requests. It's a simple wrapper for manually prepared sql requests.
"""

from collections import namedtuple


class SQLMethod:
    """Python wrapper of sql request."""

    __slots__ = (
        'record_namedtuple',
        'params_names',
        'sql_request',
    )

    def __init__(self, record_name, col_titles, params_names, sql_request):
        """Create SQLMethod object.

        Arguments:
        - record_name, col_titles: type_name and field_names of the namedtuples
            this method will return
        - params_names: names of sql request parameters. These names can be
            used later, when calling the method. Does not have to match
            db columns names.
        - sql_request: the sql request string
        """
        #self.record_name = record_name
        #self.col_titles = col_titles
        self.record_namedtuple = namedtuple(record_name, col_titles)
        self.params_names = params_names
        self.sql_request = sql_request

    def __call__(self, conn, *args, **kwargs):
        """Execute sql request, yield result records."""

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
        for raw in cur.execute(self.sql_request, req_params):
            yield self.record_namedtuple._make(raw)

    def all(self, conn, *args, **kwargs):
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
