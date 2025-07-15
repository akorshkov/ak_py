"""Methods for executing predefined sql requests.

It's quite primitive - it is NOT desined to dynamically create complex sql
requests. It's a simple wrapper for manually prepared sql requests.

Example:
records = SqlMethod(
    "SELECT u.id, u.name, a.status "
    "FROM users AS u LEFT JOIN accounts AS a "
    "  ON u.account_id = a.id ",
    order_by="u.name, u.id",
).list(
    db_conn, ("a.status", "=", 5),
)
"""

from collections import namedtuple
import contextlib
import logging


logger = logging.getLogger(__name__)


class SqlFilterCondition:
    """Contains information required to construct condition for WHERE clause"""

    PLACEHOLDER_TYPE_QUESTION, PLACEHOLDER_TYPE_PERCENT_S = 0, 1

    # to be used when constructing WHERE cluase
    _SQL_CLAUSES = {
        PLACEHOLDER_TYPE_QUESTION: {
            'PLACEHOLDER': '?',
            '=': ' = ?',
            '!=': ' != ?',
            'IN': ' IN ',
            'NOT IN': ' NOT IN ',
            'IS NULL': ' IS NULL',
            'IS NOT NULL': ' IS NOT NULL',
            'LIKE': ' LIKE ?',
            'NOT LIKE': ' NOT LIKE ?',
            '>': ' > ?',
            '<': ' < ?',
            '>=': ' >= ?',
            '<=': ' <= ?',
        },
        PLACEHOLDER_TYPE_PERCENT_S: {
            'PLACEHOLDER': '%s',
            '=': ' = %s',
            '!=': ' != %s',
            'IN': ' IN ',
            'NOT IN': ' NOT IN ',
            'IS NULL': ' IS NULL',
            'IS NOT NULL': ' IS NOT NULL',
            'LIKE': ' LIKE %s',
            'NOT LIKE': ' NOT LIKE %s',
            '>': ' > %s',
            '<': ' < %s',
            '>=': ' >= %s',
            '<=': ' <= %s',
        },
    }

    @classmethod
    def make(cls, src_obj):
        """Create SqlFilterCondition - data for a single condition of a WHERE clause.

        Argument:
        - src_obj: may be:
            - SqlFilterCondition: object will be returned as is
            - ("table.column", operation, value): args for SqlFilterCondition
                constructor
            - ("table.column", value) - same as ("table.column", "=", value)
            - "static condition" - f.e. "table1.id = table2.parent_id"
        """
        if isinstance(src_obj, SqlFilterCondition):
            return src_obj
        if isinstance(src_obj, str):
            # static condition, f.e. "table1.id = table2.parent_id"
            return SqlFieldValCondition(None, src_obj, None)
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

        return SqlFieldValCondition(field_name, op, value)

    def make_text_update_values(self, values_list, placeholders_type) -> str:
        """Prepare the part of WHERE condition.

        This method returns a string corresponding to the part of the WHERE clause
        and appends corresponding condition values to the 'values_list' argument.

        Arguments:
        - values_list: the list to append actual arguments values to
        - placeholders_type: one of
            SqlFilterCondition.PLACEHOLDER_TYPE_QUESTION
            SqlFilterCondition.PLACEHOLDER_TYPE_PERCENT_S

        Returns sql clause string and appends arguments values to 'values_list'
        """
        assert False, (
            f"Method {make_text_update_values}' not implemented in "
            f"class {type(self)}")


class SqlFieldValCondition(SqlFilterCondition):
    """Sql condition based of a value of a single field."""

    __slots__ = ('field_name', 'op', 'value')

    SUPPORTED_OPS = [
        '=', '!=', 'IN', 'NOT IN', 'IS NULL', 'IS NOT NULL', 'LIKE', 'NOT LIKE',
        '>', '<', '>=', '<=',
    ]

    def __init__(self, field_name, op, value):
        self.field_name = field_name
        self.op = op.upper()
        self.value = value
        # validate that operation and value are compartible, fix operation
        # if possible
        if self.field_name is None:
            # special case: it is hardcoded condition which does not require
            # a value. F.e. "a.parent_id = b.id"
            assert self.value is None
            self.op = " " + op + " "
        elif self.op in ('=', '!='):
            if value is None:
                self.op = 'IS NULL' if self.op == '=' else 'IS NOT NULL'
            elif isinstance(value, (list, tuple)):
                self.op = 'IN' if self.op == '=' else 'NOT IN'
        elif self.op in ('IN', 'NOT IN'):
            if not isinstance(value, (list, tuple, set)):
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
        elif self.op in ['>', '<', '>=', '<=']:
            pass
        else:
            raise ValueError(
                f"unsupported sql operation '{self.op}'. Supported operations "
                f"are: {self.SUPPORTED_OPS}")

    def make_text_update_values(self, values_list, placeholders_type) -> str:
        assert isinstance(values_list, list)
        sql_clauses = self._SQL_CLAUSES[placeholders_type]
        if self.field_name is None:
            sql = self.op
        elif self.op in ('=', '!=', '>', '<', '>=', '<='):
            values_list.append(self.value)
            sql = self.field_name + sql_clauses[self.op]
        elif self.op in ('IN', 'NOT IN'):
            assert isinstance(self.value, (list, tuple, set))
            if self.value:
                values_list.extend(self.value)
                sql = (self.field_name + sql_clauses[self.op] + "(" +
                       ", ".join(sql_clauses['PLACEHOLDER'] for _ in self.value)
                       + ")")
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


class SqlOrCondition(SqlFilterCondition):
    """Several SqlFilterCondition objects combined with 'OR'."""
    __slots__ = ('operands', )
    def __init__(self, *args, **kwargs):
        if kwargs:
            args = list(args)
            args.extend(sorted(kwargs.items()))
        self.operands = [SqlFilterCondition.make(arg) for arg in args]

    def make_text_update_values(self, values_list, placeholders_type) -> str:
        if not self.operands:
            return "FALSE"
        result = "("
        result += " OR ".join(
            op.make_text_update_values(values_list, placeholders_type)
            for op in self.operands)
        result += ")"
        return result


class SqlAndCondition(SqlFilterCondition):
    """Several SqlFilterCondition objects combined with 'AND'."""
    __slots__ = ('operands', )
    def __init__(self, *args, **kwargs):
        if kwargs:
            args = list(args)
            args.extend(sorted(kwargs.items()))
        self.operands = [SqlFilterCondition.make(arg) for arg in args]

    def make_text_update_values(self, values_list, placeholders_type) -> str:
        if not self.operands:
            return "TRUE"
        result = "("
        result += " AND ".join(
            op.make_text_update_values(values_list, placeholders_type)
            for op in self.operands)
        result += ")"
        return result


class SqlMethod:
    """Python wrapper of sql request."""

    __slots__ = (
        'sql_select_from',
        'group_by',
        'default_order_by',
        'default_as_scalars',
        'record_name',
        'fields',
        'rec_type',
        'log_ref',
    )

    _or = SqlOrCondition
    _and = SqlAndCondition

    def __init__(self, sql_select_from, *,
                 group_by=None, order_by=None, record_name=None, as_scalars=False,
                 log_ref=None):
        """Create SqlMethod object.

        Arguments:
        - sql_select_from: "SELECT ... FROM ..." part of the sql request string
        - group_by: string, to be specified if aggregation is used in the request
        - order_by: default value of "ORDER BY ..." part of sql request string.
            (it may be overridden when executing this method)
        - record_name: optional name of a namedtuple type of records returned by
            sql request.
        - as_scalars: if False, method returns records objects (usually
            namedtuples), overwise - first elements of these records.
            (it may be overridden when executing this method)
        - log_ref: optional request identifier to be mentioned in the log.

        Note: selects with HAVING are not supported yet
        """
        self.sql_select_from = sql_select_from
        self.group_by = group_by
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
        self.log_ref = log_ref

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

        filters = [SqlFilterCondition.make(x) for x in args if x is not None]

        sql = self.sql_select_from
        req_params = []
        if filters:
            sql += " WHERE " + " AND ".join(
                f.make_text_update_values(req_params, placeholders_type)
                for f in filters)
        if self.group_by:
            sql += " GROUP BY " + self.group_by
        if order_by_clause is not None:
            sql += " ORDER BY " + order_by_clause

        # and execute request
        logger.debug(
            "SQL request%s: %s ; params: %s",
            "" if self.log_ref is None else f" (#{self.log_ref})",
            sql,
            req_params,
        )
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
            - SqlMethod._or(...) - several conditions combined by 'OR'; check
                doc of 'SqlFilterCondition.make' method for description of possible
                values
            - ("table.column", operation, value) - check doc of SqlFilterCondition
                for more details
            - ("table.column", value) - same as ("table.column", "=", value)
            - None - dummy value, ignored (presence of None argument does not affect
                sql query)

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
