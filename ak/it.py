"""Tools to be used in interactive sessions,

Example of usage:
$ python
>>> from ak.it import *
>>> conf_logs()
>>> conn = http_conn("http://some.address.com")
>>> resp_data = conn("method/path", {"a": 1, "b": 2})
>>> pp(resp_data)
"""

from . import logtools as _logtools
from . import conn_http as _conn_http
from .ppobj import PrettyPrinter as _PrettyPrinter


def conf_logs(filename=".ak.log"):
    """Configure logging.

    Argument:
    - filename: if not None debug logs are saved to the file, errors - to stderr.
        If None - debug logs printed to stderr.
    """

    _logtools.log_configure(None, filename=filename)


def http_conn(address):
    """Make HttpConn object"""
    return _conn_http.HttpConn(address)


def http_bauth_conn(address, login, password):
    """Make HttpConn with basic authorization."""
    return _conn_http.bauth_conn(address, login, password)


_DFLT_PPRINTER = None


def pp(obj_to_print):
    """Generic pretty print of json-like python object."""
    global _DFLT_PPRINTER
    if _DFLT_PPRINTER is None:
        _DFLT_PPRINTER = _PrettyPrinter()
    _DFLT_PPRINTER.pretty_print(obj_to_print)
