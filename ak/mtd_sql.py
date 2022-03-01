"""Methods for executing predefined sql requests.

It's quite primitive - it is NOT desined to dynamically create complex sql
requests. It's a simple wrapper for manually prepared sql requests.
"""

from collections import namedtuple
import contextlib
import logging


logger = logging.getLogger(__name__)


class SqlFilterCondition:
    """Contains information required to construct condition for WHERE clause"""

    SUPPORTED_OPS = [
        '=', '!=', 'IN', 'NOT IN', 'IS NULL', 'IS NOT NULL', 'LIKE', 'NOT LIKE']

    PLACEHOLDER_TYPE_QUESTION, PLACEHOLDER_TYPE_PERCENT_S = 0, 1

    # to be used when constructing WHERE cluase
    _SQL_CLAUSES = {
        PLACEHOLDER_TYPE_QUESTION: {
            '=': ' = ?',
            '!=': ' != ?',
            'IN': ' IN ',
            'NOT IN': ' NOT IN ',
            'IS NULL': ' IS NULL',
            'IS NOT NULL': ' IS NOT NULL',
            'LIKE': ' LIKE ?',
            'NOT LIKE': ' NOT LIKE ?',
        },
        PLACEHOLDER_TYPE_PERCENT_S: {
            '=': ' = %s',
            '!=': ' != %s',
            'IN': ' IN ',
            'NOT IN': ' NOT IN ',
            'IS NULL': ' IS NULL',
            'IS NOT NULL': ' IS NOT NULL',
            'LIKE': ' LIKE %s',
            'NOT LIKE': ' NOT LIKE %s',
        },
    }

    def __init__(self, field_name, op, value):
        self.field_name = field_name
        self.op = op.upper()
        self.value = value
        # validate that operation and value are compartible, fix operation
        # if possible
        if self.op in ('=', '!='):
            if value is None:
                self.op = 'IS NULL' if self.op == '=' else 'IS NOT NULL'
            elif isinstance(value, (list, tuple)):
                self.op = 'IN' if self.op == '=' else 'NOT IN'
        elif self.op in ('IN', 'NOT IN'):
            if not isinstance(value, (list, tuple)):
                raise ValueError(
                    f"value {self.value} does not match sql operation {self.op}")
        elif self.op in ('IS NULL', 'IS NOT NULL'):
            if value is not None:
                raise ValueError(
                    f"value {self.value} does not match sql operation {self.op}")
        elif self.op in ('LIKE', 'NOT LIKE'):
            if not isinstance(value, str):
                raise ValueError(
                    f"value for '{self.op}' condition is not str but "
                    f"{type(value)}: {value}")
        else:
            raise ValueError(
                f"unsupported sql operation '{self.op}'. Supported operations "
                f"are: {self.SUPPORTED_OPS}")

    @classmethod
    def make(cls, src_obj):
        """Create SqlFilterCondition - data for a single condition of a WHERE clause.

        Argument:
        - src_obj: may be:
            - SqlFilterCondition: object will be returned as is
            - ("table.column", operation, value): args for SqlFilterCondition
                constructor
            - ("table.column", value) - same as ("table.column", "=", value)
        """
        if isinstance(src_obj, SqlFilterCondition):
            return src_obj
        if not isinstance(src_obj, (list, tuple)):
            raise ValueError(
                f"bad argument of type '{type(src_obj)}': {src_obj}")
        n_arg_items = len(src_obj)
        if n_arg_items == 3:
            field_name, op, value = src_obj
        elif n_arg_items == 2:
            field_name, value = src_obj
            op = '='
        else:
            raise ValueError(f"Invalid argument '{type(src_obj)}': {src_obj}")

        return cls(field_name, op, value)

    def make_text_update_values(self, values_list, placeholders_type):
        """Prepare part of WHERE condition; append necessary values to the list."""
        assert isinstance(values_list, list)
        sql_clauses = self._SQL_CLAUSES[placeholders_type]
        if self.op in ('=', '!='):
            values_list.append(self.value)
            sql = self.field_name + sql_clauses[self.op]
        elif self.op in ('IN', 'NOT IN'):
            assert isinstance(self.value, (list, tuple))
            if self.value:
                values_list.extend(self.value)
                sql = (self.field_name + sql_clauses[self.op] + "(" +
                       ", ".join("?" for _ in self.value) + ")")
            else:
                # special case: list of lossible values is empty
                sql = "0" if self.op == 'IN' else "1"
        elif self.op in ('LIKE', 'NOT LIKE'):
            values_list.append(self.value)
            sql = self.field_name + sql_clauses[self.op]
        else:
            assert self.op in ('IS NULL', 'IS NOT NULL')
            sql = self.field_name + sql_clauses[self.op]

        return sql


class SqlMethod:
    """Python wrapper of sql request."""

    __slots__ = (
        'sql_select_from',
        'default_order_by',
        'default_as_scalars',
        'record_name',
        'fields',
        'rec_type',
    )

    def __init__(self, sql_select_from, *,
                 order_by=None, record_name=None, as_scalars=False):
        """Create SqlMethod object.

        Arguments:
        - sql_select_from: "SELECT ... FROM ..." part of the sql request string
        - order_by: default value of "ORDER BY ..." part of sql request string.
            (it may be overridden when executing this method)
        - record_name: optional name of a namedtuple type of records returned by
            sql request.
        - as_scalars: if False, method returns records objects (usually
            namedtuples), overwise - first elements of these records.
            (it may be overridden when executing this method)

        Note: selects with GROUP BY are not supported yet
        """
        self.sql_select_from = sql_select_from
        self.default_order_by = order_by
        self.default_as_scalars = as_scalars
        self.record_name = record_name if record_name is not None else 'record'
        # names of the fileds of records returned by sql request. These names can
        # only be created after first sql request is performed.
        self.fields = None
        # type of the returned values. Usually it's an automatically generated
        # namedtuple (if it is possible to create a namedtuple from the field
        # names)
        self.rec_type = None

    def _execute(self, conn, args, kwargs):
        # Execute sql request, and yield result records (or scalars)

        # autodetect sql placeholders format
        # probably there shoud be a better way. temporary solution.
        conn_type_name = str(type(conn))
        if 'mysql.connector' in conn_type_name:
            placeholders_type = SqlFilterCondition.PLACEHOLDER_TYPE_PERCENT_S
        else:
            placeholders_type = SqlFilterCondition.PLACEHOLDER_TYPE_QUESTION

        order_by_clause = kwargs.pop('_order_by', self.default_order_by)
        as_scalars = kwargs.pop('_as_scalars', self.default_as_scalars)

        # convert remaining kwargs to conditions
        if kwargs:
            args = list(args)
            args.extend(sorted(kwargs.items()))

        filters = [SqlFilterCondition.make(x) for x in args]

        sql = self.sql_select_from
        req_params = []
        if filters:
            sql += " WHERE " + " AND ".join(
                f.make_text_update_values(req_params, placeholders_type)
                for f in filters)
        if order_by_clause is not None:
            sql += " ORDER BY " + order_by_clause

        # and execute request
        logger.debug("SQL request: %s ; params: %s", sql, req_params)
        # print(f"'{sql}'", req_params)
        with contextlib.closing(conn.cursor()) as cur:
            cur.execute(sql, req_params)

            if self.fields is None:
                # this is the first time actual request is performed, now we can
                # find out names of returned fields
                self._init_record_type(cur)

            if as_scalars:
                for row in cur:
                    yield row[0]
            elif self.rec_type is None:
                for row in cur:
                    yield row
            else:
                for row in cur:
                    yield self.rec_type._make(row)  # namedtuple way

    def _init_record_type(self, cur):
        # fill self.fields and self.rec_type during the first sql request
        self.fields = [x[0] for x in cur.description]
        try:
            self.rec_type = namedtuple(self.record_name, self.fields)
        except ValueError as err:
            logger.debug("can't create namedtuple for sql results: %s", str(err))

    def all(self, conn, *args, **kwargs):
        """Execute sql request, yield result records.

        Arguments:
        - conn: datanbase connection object (the one with cursor() method)
        - args: filter conditions for WHERE clause (*)
        - kwargs: filter conditions for where clause (**). Special kwargs:
            - '_as_scalars': if True then return not records, but first elemets
            - '_order_by': text for "ORDER BY' clause.

        (*) filter condition may be:
            - SqlFilterCondition object
            - ("table.column", operation, value) - check doc of SqlFilterCondition
                for more details
            - ("table.column", value) - same as ("table.column", "=", value)

        (**) name=value kwarg is interpreted as ("name", "=", value) filter condition
        """
        yield from self._execute(conn, args, kwargs)

    def list(self, conn, *args, **kwargs):
        """Execute sql request, return list of result records.

        Check doc of 'all' method for detailed description of arguments.
        """
        return list(self._execute(conn, args, kwargs))

    def one(self, conn, *args, **kwargs):
        """Execute sql request, return single record.

        Raise ValueError if not exactly one record was selected.

        Check doc of 'all' method for detailed description of arguments.
        """
        record = self.one_or_none(conn, *args, **kwargs)
        if record is None:
            raise ValueError("record not found")
        return record

    def one_or_none(self, conn, *args, **kwargs):
        """Execute sql request, return single record or None.

        Raise ValueError if more than one record was selected.

        Check doc of 'all' method for detailed description of arguments.
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
