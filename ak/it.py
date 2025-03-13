"""Ready to use gadgets to be used in interactive console.

Usage example:
>> x = {"a": 10, "b":20}
>> from ak.it import pp
>> pp(x)     # prints colored formatted text
"""

from . import ppobj


class _PPrintCommand:
    """Pretty-print console command."""

    # !!!! need tests
    _GLOBAL_PP = None

    def __init__(self):
        self._pprinter = ppobj.PrettyPrinter()

    def __call__(self, obj_to_print):
        if isinstance(obj_to_print, ppobj.PPObjBase):
            for line in obj_to_print.gen_pplines():
                print(line)
        else:
            for line in self._pprinter.gen_pplines(obj_to_print):
                print(line)

    def _get_ll_descr(self):
        # object description for 'll' command
        return "Console tools", "Command which pretty prints objects"


def pp(obj_to_print):
    """Pretty-print json-like object."""
    if _PPrintCommand._GLOBAL_PP is None:
        _PPrintCommand._GLOBAL_PP = _PPrintCommand()
    _PPrintCommand._GLOBAL_PP(obj_to_print)
