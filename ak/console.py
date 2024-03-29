"""Method for creation of interactive python consoles.

The created console has specified local objects and 'h', 'hh', 'll', 'pp' commands:
- h: somewhat more advanced help command (generates more detailed descriptions for
  ubjects created with hdoc.h_doc decorator)
- hh: more verbose version of 'h'
- ll: summary of objects in local scope
- pp: pretty-printer
"""

import sys
import code
from . import hdoc
from . import it


def start_interactive_console(
        locals_for_console=None, locals_descr=None, banner=None, exitmsg=None):
    """Start interactive console, make 'h' and 'll' commands available in it."""
    if banner is None:
        banner = f"Python {sys.version} on {sys.platform}\n"
        if locals_descr:
            banner += "Locals:\n"
            for local_name, local_descr in locals_descr:
                banner += f"{local_name:19}<- {local_descr}\n"
        banner += (
            f"Following commands from 'ak' package are available:\n"
            f"ll                 <- list local variables\n"
            f"h(obj)             <- help command\n"
            f"hh(obj)            <- help command - more detailed help\n"
            f"pp(obj)            <- pretty printer for json-like python objects\n"
        )

    if locals_for_console is None:
        locals_for_console = {}

    if 'h' not in locals_for_console:
        locals_for_console['h'] = hdoc.HCommand()

    if 'hh' not in locals_for_console:
        locals_for_console['hh'] = hdoc.HCommand(hdoc.HCommand._LEVEL_HH)

    if 'll' not in locals_for_console:
        locals_for_console['ll'] = hdoc.LLImpl(locals_for_console)

    if 'pp' not in locals_for_console:
        locals_for_console['pp'] = it._PPrintCommand()

    if exitmsg is None:
        exitmsg = "Good bye!"

    code.interact(
        banner=banner, readfunc=None, local=locals_for_console, exitmsg=exitmsg)
