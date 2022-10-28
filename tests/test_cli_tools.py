"""Test ak.cli_tools - misc helpers for command-line oriented scripts"""

import unittest
from ak.cli_tools import ArgParser


class TestArgParser(unittest.TestCase):
    """Test ak.cli_tools.ArgParser"""

    def test_std_parser(self):
        """Test standard parser - no additional arguments."""

        parser = ArgParser(description="Standard Arguments Parser")

        # script run w/o arguments
        args = parser.parse_args([])

        std_options = ['verbose', 'color', 'no_color']
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
        self.assertEqual(False, args.no_color)

        # script run with some arguments
        args = parser.parse_args(['-vv', '--color' , 'never'])

        self.assertEqual(2, args.verbose)
        self.assertEqual('never', args.color)
        self.assertEqual(False, args.no_color)

    def test_std_parser_additional_arg(self):
        """Test standard parser with additional argument"""

        parser = ArgParser(
            description="Standard Arguments Parser with additional arg")

        parser.add_argument("features", nargs="*")

        args = parser.parse_args(["f1", "f2", "f3"])

        self.assertEqual(0, args.verbose)
        self.assertEqual('auto', args.color)
        self.assertEqual(False, args.no_color)
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
        parser = ArgParser(description="std descr", _help_if_no_args=False)

        parser.parse_args([])

        self.assertTrue(
            True,
            "should get here: parse_args should not exit because "
            "_help_if_no_args option specified")

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
        self.assertEqual(False, args.no_color)
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
        parser = ArgParser(
            [("cmd1", "descr1"), ("cmd2", "descr2")],
            description="std descr", _help_if_no_args=False,
        )

        args = parser.parse_args([])

        self.assertTrue(
            True,
            "should get here: parse_args should not exit because "
            "_help_if_no_args option specified")
        self.assertEqual(
            "cmd1", args.command, "first command is default one by default, hehe")
