"""Collection of tools commonly used in cli applications.

Minimal usage example:

    parser = cli_tools.ArgParser(
        description="common tool description",
        commands=[
            ('!opts_set1', 'some options to be used in other parsers'),
            ('cmd1', 'help cmd 1'),
            ('cmd2:cmd1,opts_set1', ('descr cmd2 argument', 'cmd2 description')),
        ])

    # common arg for all commands
    parser.add_argument('-s', '--src-dir', help="arg descr")

    pars_cmd1 = parser.get_cmd_parser('cmd1')
    pars_cmd1.add_argument('-f', '--force', action='store_true', help="..")
    pars_cmd1.add_argument('items', nargs='*', help="..")

    args = parser.parse_args()
    cli_tools.std_app_configure(
        args, syntax_amends={
            'TABLE': {'BORDER': 'CYAN:bold'},
        }
    )  # configures colors and logging

    # use it to create Palette objects:
    colors_conf = ak.color.get_global_colors_config() !!!! <- use global_palette!
"""

import sys
import contextlib
from pathlib import Path
import argparse

from .color import ColorsConfig, set_global_colors_config
from .logtools import logs_configure
from . import utils


Timer = utils.Timer

class AkArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with some additional functionality.

    Using AkArgumentParser makes it possible to organize parsers into directed
    graph.

    When argument is added to AkArgumentParser the same argument is added to
    all the dependent parsers.
    """
    __slots__ = ('_dependent_parsers', )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dependent_parsers = {}

    def register_dependent(self, name, parser):
        """Register dependent parser"""
        assert name not in self._dependent_parsers
        self._dependent_parsers[name] = parser

    def add_argument(self, *args, **kwargs):
        propagate = kwargs.pop('_propagate', True)
        if propagate:
            for dependent_parser in self._dependent_parsers.values():
                dependent_parser.add_argument(*args, _propagate=False, **kwargs)
        super().add_argument(*args, **kwargs)


class ArgParser:
    """Argument parser with support of multiple subparsers for different commands.

    Common options '-v' and '--color' are present by default.
    """

    def __init__(
            self, commands=None, default_command=None, *,
            _no_log=False, _no_log_file=False, _help_if_no_args=False,
            **kwargs):
        """Create ArgParser.

        Arguments:
        - commands: optional list of sub-command descriptions. If specified, the
            parser will work in 'multi-command' mode: first argument must be a
            command name and subsequent arguments are arguments for this command.
            Each command has own arguments structure (like git has commands 'add',
            'commit', 'log', etc.). Example:
            [
              ('command_1', 'help_text'),
              ('command_2', ('help_text', 'description)),
            ]
        - default_command: if specified, it must be one of 'commands'. By default
            the first command is the default.
        - _no_log: do not display '-v' option
        - _no_log_file: does not affect arguments procesing, but in case it is
            specified, adds '_no_log_file' attribute to the result 'args'.
            (So, it behaves like a hidden argument. It's value is used
            by ak.cli_tools.std_app_configure function.)
        - _help_if_no_args: (dafault False) - indicates if help message should
            be printed if args list is empty.
        - kwargs: standard kwargs for argparse.ArgumentParser
        """
        if commands is None:
            assert default_command is None, (
                "'default_command' argument is specified, but 'commands' is not")

        if 'formatter_class' not in kwargs:
            # w/o this multi-line epilog in help text looks ugly
            kwargs['formatter_class'] = argparse.RawTextHelpFormatter

        self.parser = argparse.ArgumentParser(**kwargs)
        self._no_log = _no_log
        self._no_log_file = _no_log_file
        self._help_if_no_args = _help_if_no_args

        if commands is None:
            self.command_parsers = None
            self.common_options = None
            self.default_command = None
            self._mk_std_args(self.parser)
        else:
            self._init_multicmd_parser(commands, default_command)

    def parse_args(self, args=None, namespace=None):
        """Parse arguments.

        Arguments of this method are the same as in standard ArgumentParser.
        """
        if args is None:
            args = sys.argv[1:]

        if not args and self._help_if_no_args:
            print("appending help option")
            args.append("--help")

        if self.command_parsers is not None:
            # this is a multi-command parser
            # some black magic is required to detect default command
            first_arg = args[0] if args else None
            if all(
                first_arg not in choices
                for choices in [['-h', '--help'], self.command_parsers]
            ):
                args.insert(0, self.default_command)

        args = self.parser.parse_args(args, namespace)
        if self._no_log_file:
            args._no_log_file = True

        if args.no_color:
            args.color = False
        del args.no_color

        return args

    def _mk_std_args(self, parser):
        # add 'standard' arguments to a specified parser
        if not self._no_log:
            parser.add_argument(
                "-v", "--verbose", default=0, action="count",
                help="increase log verbocity (3 levels)")

        color_grp = parser.add_mutually_exclusive_group()

        color_grp.add_argument(
            "--color", default='auto', nargs="?",
            choices=["auto", "always", "yes", "1", "never", "no", "0"],
            help=(
                "when show colored output. "
                "'--color' is the same as '--color=always'. "
                "Default value is 'auto'.")
        )

        color_grp.add_argument(
            "--no-color", action='store_true',
            help="the same as '--color=never'. Overrides '--color' option"
        )

    def _init_multicmd_parser(self, commands, default_command):
        # configure self.parser to process arguments for different commands
        # (like git has different commands ('commit', 'log', 'push', etc.) and
        # these commands have different arguments)

        assert commands

        # parent for all other parsers, contains common options
        self.common_options = argparse.ArgumentParser(
            # add_help=False,
            description="Common options")
        self._mk_std_args(self.common_options)

        commands_names = []  # names of commands
        self.command_parsers = {}  # {parser_name: parser}

        subparsers = self.parser.add_subparsers(
            parser_class=AkArgumentParser,
            dest='command', help="Available commands")

        for command, cmd_attrs in commands:
            if isinstance(cmd_attrs, str):
                help_text = cmd_attrs
                descr = None
            else:
                help_text, descr = cmd_attrs

            # command may look like "!cmd:parent,parent1"
            chunks = command.split(':', maxsplit=1)
            if len(chunks) == 2:
                command, parents = chunks
            else:
                parents = ""

            is_internal = command.startswith('!')
            if is_internal:
                command = command[1:]

            parser_name = command
            assert parser_name

            parents = {
                pp
                for p in parents.split(',') if (pp := p.strip())
            }

            assert parser_name not in self.command_parsers, (
                f"duble declaration of subparser '{parser_name}'")

            for p in parents:
                assert p in self.command_parsers, (
                    f"unknown parent parser '{p}' specified for '{parser_name}'")

            if is_internal:
                cmd_parser = AkArgumentParser(
                    parents=[self.common_options, ],
                    add_help=False,
                    description=descr or help_text)
            else:
                cmd_parser = subparsers.add_parser(
                    parser_name,
                    parents=[self.common_options, ],
                    add_help=False,
                    help=help_text, description=descr)
                commands_names.append(parser_name)

            # register newly created cmd_parser in parents...
            for p in parents:
                parent_parser = self.command_parsers[p]
                parent_parser.register_dependent(parser_name, cmd_parser)
                # ... and all ascendants
                for parser in self.command_parsers.values():
                    if p in parser._dependent_parsers:
                        parser.register_dependent(parser_name, cmd_parser)

            self.command_parsers[parser_name] = cmd_parser

        if default_command is None and commands_names:
            default_command = commands_names[0]
        self.default_command = default_command

    def add_argument(self, *args, **kwargs):
        """Declare argument.

        Same syntax as in stadard ArgumentParser.

        In case of multi-command parser adds the argument to all commands.
        """
        if self.command_parsers is None:
            # self is usual one-command parser
            self.parser.add_argument(*args, **kwargs)
        else:
            for cmd_parser in self.command_parsers.values():
                cmd_parser.add_argument(*args, _propagate=False, **kwargs)

    def get_cmd_parser(self, command_name):
        """Get parser corresponding to a command."""
        assert self.command_parsers is not None, (
            "method not applicable for this is a single-command argparser")
        try:
            return self.command_parsers[command_name]
        except KeyError:
            avail_commands = ", ".join(sorted(self.command_parsers.keys()))
            raise ValueError(
                f"Command '{command_name}' is not configured. "
                f"Configured commands: {avail_commands}")


def std_app_configure(
        args, *,
        global_colors_config_class=None,
        syntax_amends=None,
):
    """Perform standard configuration of script

    Arguments:
    - args: parsed command-line arguments; expected args in a format produced
        by ak.cli_tools.ArgParser.
    - global_colors_config_class: optional ak.color.ColorsConfig-derived class,
        to be used if not a standard colors config is used
    - syntax_amends: optional dictionary of amendments to colors
        config implemented in global colors config, or list of such dictionaries.

    Method adds 'color_stdout' boolean attribute to args: rest of script should use
    this value to decide if colored text should be produced.
    """
    # 1. process 'use colors' options
    if not args.color or args.color.lower() in ('never', 'no', '0'):
        color_stdout = False
    elif args.color.lower() in ('always', 'yes', '1'):
        color_stdout = True
    else:
        color_stdout = sys.stdout.isatty()

    args.color_stdout = color_stdout

    # 2. configure global colors config
    conf_class = global_colors_config_class or ColorsConfig

    syntax_amends = syntax_amends or []
    if isinstance(syntax_amends, dict):
        syntax_amends = [syntax_amends, ]

    global_colors_conf = conf_class(*syntax_amends, no_color=not args.color_stdout)
    set_global_colors_config(global_colors_conf)

    # 3. configure logging
    if getattr(args, '_no_log', False):
        # all logs explicitely turned off
        return

    if getattr(args, '_no_log_file', False):
        # no log file
        log_filename = None
    else:
        # autodetect log file name
        script_name = sys.argv[0]
        log_filename = Path(script_name).stem  # script name w/o extention
        if not log_filename.startswith("."):
            log_filename = "." + log_filename
        log_filename += ".log"

    verbocity = getattr(args, 'verbose', 0)

    logs_configure(verbocity, filename=log_filename, use_colors=color_stdout)


@contextlib.contextmanager
def file_or_stdout(filename, mode="w"):
    """Yields either an open file or stdout object.

    Is a context manager - if necessary closes the file after use.

    Arguments:
    - filename: name of the file to open or None (to use stdout)
    - mode: either "w" or "wb" (it will be possible to write either text or bytes to
        returned object)
    """
    assert mode in ["w", "wb"]
    if filename is None:
        f = sys.stdout if mode == "w" else sys.stdout.buffer
    else:
        f = open(filename, mode, encoding="utf-8")

    try:
        yield f
    finally:
        if filename is not None:
            f.close()
