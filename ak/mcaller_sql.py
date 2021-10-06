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
        self.component = component


def method_sql(component=None):
    """decorator to mark method as a 'wrapper' around sql request."""

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
    """Base class for "sql method callers".

    Derived class should look like:
    class MyCaller(MCallerSql):

        _SQL_MTD_1 = SqlMethod(....)

        def __init__(self, ...):
            self.sql_dbs_addrs = {
                # component_name -> db-specific info required to connect db
            }

        def _make_sql_conn(self, component_name, conn_info):
            # conn_info is self.sql_dbs_addrs[component_name]
            # create real db connection and return it
            return conn

        @method_sql('componentX')
        def get_something_from_db(self, some_args):
            db_conn = self.get_sql_conn()
            return self.SQL_MTD_1.one_or_none(db_conn, some_args)

    In case component names are not used in 'method_sql' decorators
    a single self.sql_db_addr can be used instead of a self.sql_dbs_addrs dict.
    """

    def get_sql_conn(self):
        """Returns sql connection to be used in current sql wrapper method.

        Returned sql connection depends on 'method_sql' metadata of caller.
        So this method uses some 'inspect' magic to find this metadata.
        """
        # pylint: disable=no-member
        method_meta = self.get_mcaller_meta()  # 'inspect' magic is in there

        assert isinstance(method_meta, MCallerMetaSqlMethod), (
            "Method 'get_sql_conn' can only be called from sql request wrappers"
        )

        if not hasattr(self, '_mc_sql_conns'):
            setattr(self, '_mc_sql_conns', {})

        if method_meta.component not in self._mc_sql_conns:
            # get the connection info
            conn_map_is_used = hasattr(self, 'sql_dbs_addrs')
            single_conn_is_used = hasattr(self, 'sql_db_addr')
            if not(conn_map_is_used or single_conn_is_used):
                raise ValueError(
                    f"obj of class {type(self)} has both 'sql_db_addr' "
                    f"should have database connection information stored in "
                    f"either 'sql_db_addr' attribute or in 'sql_dbs_addrs' "
                    f"dictionary (in case sql methods have 'component' property.)")
            if conn_map_is_used and single_conn_is_used:
                raise ValueError(
                    f"obj of class {type(self)} has both 'sql_db_addr' "
                    f"'sql_dbs_addrs' attributes. If 'sql_dbs_addrs' is used "
                    f"the information about db connection for methods w/o "
                    f"specified component should be stored in "
                    f"sql_dbs_addrs[None].")
            if conn_map_is_used:
                if method_meta.component not in self.sql_dbs_addrs:
                    raise ValueError(
                        f"obj of class {type(self)}: db address of component "
                        f"'{method_meta.component}' is not found in "
                        f"'sql_dbs_addrs' dictionary.")
                db_addr = self.sql_dbs_addrs[method_meta.component]
            else:
                if method_meta.component is not None:
                    raise ValueError(
                        f"obj of class {type(self)} has sql method with "
                        f"component '{method_meta.component}', but does not "
                        f"have 'sql_dbs_addrs' attribute")
                db_addr = self.sql_db_addr

            self._mc_sql_conns[method_meta.component] = self._make_sql_conn(
                method_meta.component, db_addr)

        return self._mc_sql_conns[method_meta.component]

    def _make_sql_conn(self, _component_name, db_addr):
        # create actual db connection for specified component
        # (db_addr is db address information fetched from self.sql_dbs_addrs
        # or self.sql_db_addr)
        #
        # Default implementation assumes that db_addr is already an actual
        # db connection. Override in derived class if required
        return db_addr

    def _make_bm_notes_sql(self, bound_method, palette) -> BoundMethodNotes:
        # create BoundMethodNotes for bound sql-request method (method
        # decorated with 'method_sql')
        assert hasattr(bound_method, '_mcaller_meta')
        method_meta = bound_method._mcaller_meta
        for attr in ['component']:
            # '_make_bm_notes_sql' must have been specified in method_meta,
            # so method_meta must have these attributes
            assert hasattr(method_meta, attr)

        if hasattr(self, 'sql_dbs_addrs'):
            if method_meta.component in self.sql_dbs_addrs:
                return BoundMethodNotes(True, "", None)
        elif hasattr(self, 'sql_db_addr'):
            if method_meta.component is None:
                return BoundMethodNotes(True, "", None)

        # connection to specified component not available
        if method_meta.component is not None:
            return BoundMethodNotes(
                False, '<n/a>',
                f"db component '{method_meta.component}' is not configured")
        return BoundMethodNotes(
            False, '<n/a>', "db connection is not configured")
