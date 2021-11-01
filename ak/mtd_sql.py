"""Methods for executing predefined sql requests.

It's quite primitive - it is NOT desined to dynamically create complex sql
requests. It's a simple wrapper for manually prepared sql requests.
"""

from collections import namedtuple
import contextlib
import logging


logger = logging.getLogger(__name__)


class SqlMethod:
    """Python wrapper of sql request."""

    __slots__ = (
        'sql_request',
        'params_names',
        'record_name',
        'fields',
        'rec_type',
    )

    def __init__(self, sql_request, params_names=None, record_name='record'):
        """Create SqlMethod object.

        Arguments:
        - sql_request: the sql request string
        - params_names: list of names of sql request parameters. These names can be
            used later, when calling the method. Does not have to match
            db columns names.
        - record_name: optional name of a namedtuple type of records returned by
            sql request.
        """
        self.sql_request = sql_request
        self.params_names = params_names
        self.record_name = record_name
        # named of the fileds of records returned by sql request. These names can
        # only be created after first sql request is performed.
        self.fields = None
        # type of the returned values. Usually it's an automatically generated
        # namedtuple (if it is possible to create a namedtuple from the field
        # names)
        self.rec_type = None

    def _execute(self, conn, args, kwargs):
        # Execute sql request, yield result records
        # rsult records are either tuples or namedtuples

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
        logger.debug("SQL request: %s ; params: %s", self.sql_request, req_params)
        with contextlib.closing(conn.cursor()) as cur:
            cur.execute(self.sql_request, req_params)

            if self.fields is None:
                # this is the first time actual request is performed, now we can
                # find out names of returned fields
                self._init_record_type(cur)

            if self.rec_type is None:
                for row in cur:
                    yield row
            else:
                for row in cur:
                    yield self.rec_type._make(row)

    def _init_record_type(self, cur):
        # fill self.fields and self.rec_type during the first sql request
        self.fields = [x[0] for x in cur.description]
        try:
            self.rec_type = namedtuple(self.record_name, self.fields)
        except ValueError as err:
            logger.debug("can't create namedtuple for sql results: %s", str(err))

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

    @staticmethod
    def records_mmap(records, *key_names, unique=True):
        """records -> {key1: {key2: ... {keyN: record}...}}

        If unique argument is not true:
        records -> {key1: {key2: ... {keyN: [record, ]}...}}
        """
        ret_val = {}
        last_key_id = len(key_names) - 1

        for record in records:
            cur_dict = ret_val
            for i, attr_name in enumerate(key_names):
                val = getattr(record, attr_name)
                if i == last_key_id:
                    if unique:
                        # leaf element is a single record
                        assert val not in cur_dict, (
                            f"duplicate records {record} and {cur_dict[val]} found. "
                            f"(key attributes: {key_names}")
                        cur_dict[val] = record
                    else:
                        # leaf element is a list
                        cur_dict.setdefault(val, []).append(record)
                else:
                    cur_dict = cur_dict.setdefault(val, {})

        return ret_val
