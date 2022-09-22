"""Collection of tools commonly used in cli applications."""

import sys
import contextlib
from pathlib import Path
import argparse

from .logtools import logs_configure


class ArgParser:
    """Argument parser with support of multiple subparsers for different commands.

    Common options '-v' and '--color' are present by default.
    """

    def __init__(
            self, commands=None, default_command=None, *,
            _no_log=False, _no_log_file=False,
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
        - _no_log: do not display '-v' option
        - _no_log_file: does not affect arguments procesing, but in case it is
            specified, adds '_no_log_file' attribute to the result 'args'.
            (So, it behaves like a hidden argument. It's value is used
            by ak.cli_tools.std_app_conf function.
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
        if self.command_parsers is not None:
            # this is a multi-command parser
            # some black magic is required to detect default command
            if args is None:
                args = sys.argv[1:]

            if not args:
                args.append("--help")
            else:
                first_arg = args[0]
                if all(
                    first_arg not in choices
                    for choices in [['-h', '--help'], self.command_parsers]
                ):
                    args.insert(0, self.default_command)

        args = self.parser.parse_args(args, namespace)
        if self._no_log_file:
            args._no_log_file = True

        return args

    def _mk_std_args(self, parser):
        # add 'standard' arguments to a specified parser
        if not self._no_log:
            parser.add_argument(
                "-v", "--verbose", default=0, action="count",
                help="increase log verbocity (3 levels)")

        parser.add_argument(
            "--color", default='auto', nargs="?",
            choices=["auto", "always", "yes", "1", "never", "no", "0"],
            help=(
                "when show colored output. '--color' is the same as '--color=always'. "
                "Default value is 'auto'.")
        )

        parser.add_argument(
            "--no-color", action='store_true',
            help="the same as '--color=never'. Overrides '--color' option"
        )

    def _init_multicmd_parser(self, commands, default_command):
        # configure self.parser to process arguments for different commands
        # (like git has different commands ('commit', 'log', 'push', etc.) and
        # these commands have different arguments)
        if default_command is None:
            default_command = commands[0][0]
        self.default_command = default_command

        subparsers = self.parser.add_subparsers(
            dest='command', help="Available commands")

        # some options which are applicable for all commands
        self.common_options = argparse.ArgumentParser(
            add_help=False, description="Common options")

        self._mk_std_args(self.common_options)

        self.command_parsers = {}
        for command, cmd_attrs in commands:
            if isinstance(cmd_attrs, str):
                help_text = cmd_attrs
                descr = None
            else:
                help_text, descr = cmd_attrs
            cmd_parser = subparsers.add_parser(
                command,
                parents=[self.common_options],
                help=help_text, description=descr)
            self.command_parsers[command] = cmd_parser

    def add_argument(self, *args, **kwargs):
        """Declare argument.

        Same syntax as in stadard ArgumentParser.

        In case multi-command parser adds the argument to all commands.
        """
        if self.command_parsers is None:
            # self is usual one-command parser
            self.parser.add_argument(*args, **kwargs)
        else:
            for cmd_parser in self.command_parsers.values():
                cmd_parser.add_argument(*args, **kwargs)

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


def std_app_conf(args):
    """Perform standard configuration of script

    Arguments:
    - args: parsed command-line arguments; expected args in a format produced
        by ak.cli_tools.ArgParser.

    Method adds 'color_stdout' boolean attribute to args: rest of script should use
    this value to decide if colored text should be produced.
    """
    # 1. process 'use colors' options
    if args.color.lower() in ('never', 'no', '0'):
        color_stdout = False
    elif args.color.lower() in ('always', 'yes', '1'):
        color_stdout = True
    else:
        color_stdout = sys.stdout.isatty()

    args.color_stdout = color_stdout

    # 1. configure logging
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
