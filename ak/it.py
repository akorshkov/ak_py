"""Method for creatoin of interactive sessions.

The created console has specified local objects and 'h', 'll', 'pp' functions.
"""

import sys
import code
from . import ppobj
from . import hdoc


class _PPrintCommand:
    """Pretty-print console command.

    If object to print is pretty-printable (instance of ppobj.PPObj),
    the object generates own description. For other objects generic
    PrettyPrinter is used.
    """

    def __init__(self):
        self._pprinter = ppobj.PrettyPrinter()

    def __call__(self, obj_to_print):
        if isinstance(obj_to_print, ppobj.PPObj):
            for line in obj_to_print.gen_pplines():
                print(line)
        else:
            for line in self._pprinter.gen_pplines(obj_to_print):
                print(line)

    def _get_ll_descr(self):
        # object description for 'll' command
        return "Console tools", "Command which pretty prints objects"


def start_interactive_console(locals_for_console=None, banner=None, exitmsg=None):
    """Start interactive console, make 'h' and 'll' commands available in it."""
    if banner is None:
        banner = (
            f"Python {sys.version} on {sys.platform}\n"
            f"Following commands from 'ak' package are available:\n"
            f"ll                 <- list local variables\n"
            f"h(obj)             <- help command\n"
            f"pp(obj)            <- pretty printer for json-like python objects\n"
        )

    if locals_for_console is None:
        locals_for_console = {}

    if 'h' not in locals_for_console:
        locals_for_console['h'] = hdoc.HCommand()

    if 'll' not in locals_for_console:
        locals_for_console['ll'] = hdoc.LLImpl(locals_for_console)

    if 'pp' not in locals_for_console:
        locals_for_console['pp'] = _PPrintCommand()

    if exitmsg is None:
        exitmsg = "Good bye!"

    code.interact(
        banner=banner, readfunc=None, local=locals_for_console, exitmsg=exitmsg)
