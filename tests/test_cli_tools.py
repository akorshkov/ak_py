"""Test ak.cli_tools - misc helpers for command-line oriented scripts"""

import unittest
import sys
import io
from ak.cli_tools import ArgParser


class TestArgParser(unittest.TestCase):
    """Test ak.cli_tools.ArgParser"""

    class UnexpectedSuccessParsingArgs(Exception):
        """Raised in case arg parser has not failed as expected"""
        def __init__(self, args):
            """'args' - result of successfull 'parse_args'"""
            super().__init__(
                f"unexpected success parsing args. Result: {args}")
            self.result_args = args

    def _assert_argparser_fails(self, parser, arguments):
        # make sure parser can't fails to process given arguments
        # return captured output
        # in case of successfull parse raises exception
        new_out, new_err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        parse_failed = False
        args = None  # result of 'parse_args'
        try:
            sys.stdout, sys.stderr = new_out, new_err
            try:
                args = parser.parse_args(arguments)
            except SystemExit:
                parse_failed = True
        finally:
            sys.stdout, sys.stderr = old_out, old_err

        if not parse_failed:
            raise self.UnexpectedSuccessParsingArgs(args)

        new_out.seek(0)
        new_err.seek(0)
        return new_out.read(), new_err.read()

    def test_std_parser(self):
        """Test standard parser - no additional arguments."""

        parser = ArgParser(description="Standard Arguments Parser")

        # script run w/o arguments
        args = parser.parse_args([])

        std_options = ['verbose', 'color']
        missing_options = [
            opt for opt in std_options
            if not hasattr(args, opt)
        ]
        self.assertEqual(
            0, len(missing_options),
            f"Following standard options are not present in parsed args {args}: "
            f"{missing_options}")
        self.assertEqual(0, args.verbose)
        self.assertEqual('auto', args.color)
        self.assertFalse(hasattr(args, 'no_color'))

        # script run with some arguments
        args = parser.parse_args(['-vv', '--color' , 'never'])

        self.assertEqual(2, args.verbose)
        self.assertEqual('never', args.color)
        self.assertFalse(hasattr(args, 'no_color'))

    def test_std_parser_additional_arg(self):
        """Test standard parser with additional argument"""

        parser = ArgParser(
            description="Standard Arguments Parser with additional arg")

        parser.add_argument("features", nargs="*")

        args = parser.parse_args(["f1", "f2", "f3"])

        self.assertEqual(0, args.verbose)
        self.assertEqual('auto', args.color)
        self.assertFalse(hasattr(args, 'no_color'))
        self.assertEqual(["f1", "f2", "f3"], args.features)

    def test_no_log_options(self):
        """Test _no_log and _no_log_file options"""

        # no options specified
        parser = ArgParser(description="std descr")
        args = parser.parse_args([])
        self.assertTrue(
            not hasattr(args, '_no_log_file'),
            "by default this value should not be present")
        self.assertEqual(0, args.verbose)

        # _no_log_file options specified
        parser = ArgParser(
            description="std descr", _no_log_file=True)
        args = parser.parse_args([])
        self.assertEqual(True, args._no_log_file)
        self.assertEqual(0, args.verbose)

        # _no_log options specified
        parser = ArgParser(description="std descr", _no_log=True)
        args = parser.parse_args([])
        self.assertTrue(
            not hasattr(args, '_no_log_file'),
            "by default this value should not be present")
        self.assertTrue(
            not hasattr(args, 'verbose'),
            "this option is disabled explicitely by '_no_log' arg")

    def test_empty_args_list(self):
        """Test _help_if_no_args ArgParser option."""

        # 1. it is possible to print help if no options specified.
        # by default this option is 'off'
        parser = ArgParser(description="std descr")
        args = parser.parse_args([])
        self.assertIn('verbose', args)  # just to make sure args parsed

        # 2. but it's possible to turn it on:
        parser = ArgParser(description="std descr", _help_if_no_args=True)

        # actually this is not a fail, just "print help and exit"
        out_msg, _err_msg = self._assert_argparser_fails(parser, [])
        self.assertIn("show this help message and exit", out_msg)

    def test_multicommand_argparse(self):
        """Test usual scenario with multi-command argparser"""

        parser = ArgParser(
            [
                ('cmd1', "command 1"),
                ('cmd2', "command 2"),
                ('cmd3', "command 3"),
            ],
            default_command='cmd2',
            description="Multi-command args",
        )

        # add common option
        parser.add_argument(
            "-l", "--details-level", default=0, action="count",
            help="increase details level")

        # add argument for cmd3 only
        cmd3_parser = parser.get_cmd_parser('cmd3')
        cmd3_parser.add_argument("simplearg", help="simple arg for cmd3")

        # check processing default command
        args = parser.parse_args(["-l", "-v"])
        self.assertEqual('cmd2', args.command, "command not specified - use default")
        self.assertEqual(1, args.details_level)
        self.assertEqual(1, args.verbose)
        self.assertTrue(not hasattr(args, 'simplearg'), "this arg is for cmd3 only")

        # check processing 'cmd3' arguments
        args = parser.parse_args(["cmd3", "-ll", "17"])
        self.assertEqual('cmd3', args.command)
        self.assertEqual(0, args.verbose)
        self.assertEqual('auto', args.color)
        self.assertFalse(
            hasattr(args, 'no_color'),
            "--no-color option affects args.color value, not args.no_color")
        self.assertEqual(2, args.details_level)
        self.assertEqual("17", args.simplearg)

    def test_no_log_options_in_multicmd(self):
        """Test _no_log and _no_log_file options in multi-cmd parser"""

        # no options specified
        parser = ArgParser(
            [
                ("c1", "help1"),
                ("c2", "help2"),
            ],
            description="std descr")
        parser.add_argument("thearg", help="some arg")
        args = parser.parse_args(['dummy'])
        self.assertTrue(
            not hasattr(args, '_no_log_file'),
            "by default this value should not be present")
        self.assertEqual(0, args.verbose)

        # _no_log_file options specified
        parser = ArgParser(
            [
                ("c1", "help1"),
                ("c2", "help2"),
            ],
            description="std descr", _no_log_file=True)
        parser.add_argument("thearg", help="some arg")
        args = parser.parse_args(['dummy'])
        self.assertEqual(True, args._no_log_file)
        self.assertEqual(0, args.verbose)

        # _no_log options specified
        parser = ArgParser(
            [
                ("c1", "help1"),
                ("c2", "help2"),
            ],
            description="std descr", _no_log=True)
        parser.add_argument("thearg", help="some arg")
        args = parser.parse_args(['dummy'])
        self.assertTrue(
            not hasattr(args, '_no_log_file'),
            "by default this value should not be present")
        self.assertTrue(
            not hasattr(args, 'verbose'),
            "this option is disabled explicitely by '_no_log' arg")

    def test_empty_args_list_multicmd_parser(self):
        """Test _help_if_no_args ArgParser option."""

        # 1. it is possible to print help if no options specified.
        # by default this option is 'off'
        # Arguments will be parsed, default command will be executed
        parser = ArgParser(
            [("cmd1", "descr1"), ("cmd2", "descr2")],
            description="std descr",
        )

        args = parser.parse_args([])
        self.assertEqual(
            'cmd1', args.command,
            "default command 'cmd1' selected because no arguments "
            "specified and _help_if_no_args is not specified"
        )

        # 2. alternatively, show help if no arguments
        parser = ArgParser(
            [("cmd1", "descr1"), ("cmd2", "descr2")],
            description="std descr", _help_if_no_args=True,
        )
        out_msg, _err_msg = self._assert_argparser_fails(parser, [])
        # help in this case should mention both commands
        self.assertIn("show this help message and exit", out_msg)
        self.assertIn("cmd1", out_msg)
        self.assertIn("cmd2", out_msg)

    def test_multicmd_tree_structure(self):
        """test mutli-cmd parser with nested sub-parsers."""

        parser = ArgParser([
            ("cmd1", ("help1", "descr1")),
            ("!options", "common options"),
            ("cmd2:cmd1,options", "cmd2 descr"),
            ("cmd3:cmd2", "cmd3 descr"),
            ("cmd4:cmd1", "cmd4 descr"),
        ])

        pars_cmd1 = parser.get_cmd_parser('cmd1')
        pars_cmd1.add_argument('--arg-c1-a1', help="cmd1 arg1")

        pars_opts = parser.get_cmd_parser('options')
        pars_opts.add_argument('--arg-opt', help="ops arg")

        pars_cmd2 = parser.get_cmd_parser('cmd2')
        pars_cmd2.add_argument('--arg-c2-a2', help="cmd2 arg2")

        # test cmd1
        args = parser.parse_args(["cmd1", ])
        self.assertIn('arg_c1_a1', args) # arg explicitely added to cmd1

        # test options
        # it is 'internal' parser, no command associated with it
        _out_msg, err_msg = self._assert_argparser_fails(parser, ["options", ])
        self.assertIn("invalid choice: 'options'", err_msg)

        # test cmd2
        # it should contain arguments added to 'cmd1' and 'options'
        args = parser.parse_args(["cmd2", ])
        self.assertIn('arg_opt', args)
        self.assertIn('arg_c1_a1', args)
        self.assertIn('arg_c2_a2', args)

        # test cmd3
        # it can process same arguments as cmd2
        args = parser.parse_args(["cmd3", ])
        self.assertIn('arg_opt', args)
        self.assertIn('arg_c1_a1', args)
        self.assertIn('arg_c2_a2', args)

        # test cmd4
        # it should have no args from 'options' parser
        args = parser.parse_args(["cmd4", ])
        self.assertNotIn('arg_opt', args)
        self.assertIn('arg_c1_a1', args)
        self.assertNotIn('arg_c2_a2', args)
