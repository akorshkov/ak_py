"""Test LL Parser"""

import unittest
from ak import llparser
from ak.llparser import LLParser, _Tokenizer, TElement


class TestParserTokenizer(unittest.TestCase):
    """Test tokenizer used by LLParser"""

    def test_tokenizer(self):
        """Test tokenizer"""

        tokenizer = _Tokenizer(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |"(?P<DQ_STRING>[^"]*)"
            |'(?P<SQ_STRING>[^']*)'
            |(?P<COMMENT>//.*$)
            |(?P<PLUS>\+)
            |(?P<MINUS>-)
            |(?P<MULT>\*)
            |(?P<DIV>/)
            |(?P<BR_OPEN>\()
            |(?P<BR_CLOSE>\))
            """,
            keywords = {
                ('WORD', 'class'): 'CLASS',
                ('WORD', 'import'): 'IMPORT',
            },
            synonyms = {
                'PLUS': '+',
                'MINUS': '-',
                'MULT': '*',
                'DIV': '/',
                'BR_OPEN': '(',
                'BR_CLOSE': ')',
                'DQ_STRING': 'STRING',
                'SQ_STRING': 'STRING',
            },
        )

        tokens = list(tokenizer.tokenize(
            """
            aaa "bb" '+' - xx* '+ -' / () x86  \n \t     c

            c class // a + b
            """)
        )
        self.assertEqual(15, len(tokens), str(tokens))

        tokens_names = [t.name for t in tokens]
        tokens_values = [t.value for t in tokens]

        self.assertEqual(
            [
                'WORD', 'STRING', 'STRING', '-', 'WORD', '*', 'STRING', '/', '(', ')',
                'WORD', 'WORD', 'WORD', 'CLASS', '$END$',
            ], tokens_names)
        self.assertEqual(
            [
                'aaa', 'bb', '+', '-', 'xx', '*', '+ -', '/', '(', ')', 'x86', 'c',
                'c', 'class', None,
            ], tokens_values)


class TestArithmeticsParser(unittest.TestCase):
    """Test simple parser of arithmetic operations."""

    def _make_test_parser(self, debug=False):
        # make the parser

        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<PLUS>\+)
            |(?P<MINUS>-)
            |(?P<MULT>\*)
            |(?P<DIV>/)
            |(?P<BR_OPEN>\()
            |(?P<BR_CLOSE>\))
            """,
            synonyms={
                'PLUS': '+',
                'MINUS': '-',
                'MULT': '*',
                'DIV': '/',
                'BR_OPEN': '(',
                'BR_CLOSE': ')',
            },
            keywords=None,
            space_tokens={'SPACE'},
            start_symbol_name='E',
            end_token_name='$END$',
            productions={
                'E': [
                    ('SLAG', '+', 'E'),
                    ('SLAG', '-', 'E'),
                    ('SLAG', )
                ],
                'SLAG': [
                    ('(', 'E', ')'),
                    ('WORD', '*', 'SLAG'),
                    ('WORD', '/', 'SLAG'),
                    ('WORD',),
                ]
            },
            debug=debug,
        )
        return parser

    def test_simple_operations(self):
        """Parse very simple expressions."""
        parser = self._make_test_parser(debug=False)

        # 1. one word
        x = parser.parse("aa")
        # x.printme()
        x.cleanup()
        # x.printme()
        self.assertTrue(isinstance(x, TElement), f"{type(x)}")
        self.assertEqual(('E', 'WORD'), x.signature())
        self.assertEqual('aa', x.value[0].value)

        # 2. single '+'
        x = parser.parse("aa + bb")
        x.cleanup()
        self.assertEqual(('E', 'WORD', '+', 'WORD'), x.signature())

        # 3. single '*'
        x = parser.parse("aa * bb")
        x = x.cleanup()
        self.assertEqual(('E', 'WORD', '*', 'WORD'), x.signature())

    def test_multiple_operations(self):
        """parse expression with multiple aoprations"""
        parser = self._make_test_parser()
        # parser.print_detailed_descr()

        x = parser.parse("aa + bb * cc + dd")
        x.cleanup()

        self.assertTrue(isinstance(x, TElement), f"{type(x)}")
        self.assertEqual(('E', 'WORD', '+', 'E'), x.signature())

        first_slag = x.value[0]
        self.assertEqual(('WORD', ), first_slag.signature())
        self.assertEqual('aa', first_slag.value)

        second_slag = x.value[2]
        self.assertEqual(('E', 'SLAG', '+', 'WORD'), second_slag.signature())

        self.assertEqual(
            ('SLAG', 'WORD', '*', 'WORD'),
            second_slag.value[0].signature())

    def test_expression_with_braces(self):
        """Test more complex valid expression with braces"""
        parser = self._make_test_parser()
        x = parser.parse("(a) + ( b - c * d ) + ( x )")
        x.cleanup()
        # x.printme()
        self.assertEqual(('E', 'SLAG', '+', 'E'), x.signature())

        first_slag = x.value[0]
        self.assertEqual(('SLAG', '(', 'WORD', ')'), first_slag.signature())

        second_slag = x.value[2]
        self.assertEqual(('E', 'SLAG', '+', 'E'), second_slag.signature())

    def test_bad_expression(self):
        # test parsing bad expressions
        parser = self._make_test_parser()

        with self.assertRaises(llparser.ParsingError):
            parser.parse("aa )")


class TestListParser(unittest.TestCase):
    """Test simple parser of list."""

    def test_list_parser(self):
        """Test simple parser of list."""
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<COMMA>,)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            """,
            synonyms={
                'COMMA': ',',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
            },
            productions={
                'E': [
                    ('LIST',),
                ],
                'LIST': [
                    ('[', 'WORD', 'OPT_LIST', ']'),
                ],
                'OPT_LIST': [
                    (',', 'WORD', 'OPT_LIST'),
                    (',', ),
                    None,
                ],
            },
            #debug=True,
        )

        x = parser.parse("[ a, b, c, d]")
        x.cleanup(keep_symbols={'LIST'})
        self.assertEqual(('E', 'LIST'), x.signature())

        x = parser.parse("[a, b, c,]")
        x.cleanup(keep_symbols={'LIST'})
        self.assertEqual(('E', 'LIST'), x.signature())


class TestBadGrammar(unittest.TestCase):
    """Test misc problems with grammar."""

    def test_resursive_grammar(self):
        """GrammarIsRecursive should be reported in parser constructor."""
        with self.assertRaises(llparser.GrammarIsRecursive) as exc:
            LLParser(
                r"""
                (?P<SPACE>\s+)
                |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
                """,
                productions={
                    'E': [
                        ('X', 'WORD'),
                    ],
                    'X': [
                        ('NN', ),
                    ],
                    'NN': [
                        ('GG', 'TT', 'WORD'),
                        None,
                    ],
                    'GG': [
                        ('WORD', ),
                        None,
                    ],
                    'TT': [
                        ('X', 'WORD'),
                        None,
                    ],
                },
            )

        err_msg = str(exc.exception)
        self.assertIn("'NN' -> ['GG', <'TT'>, 'WORD']", err_msg)


class TestParserWithNullProductions(unittest.TestCase):
    """Test arithmetic parser with null productions"""

    def test_parser_null_productins(self):
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<PLUS>\+)
            |(?P<MULT>\*)
            |(?P<BR_OPEN>\()
            |(?P<BR_CLOSE>\))
            """,
            synonyms={
                'PLUS': '+',
                'MULT': '*',
                'BR_OPEN': '(',
                'BR_CLOSE': ')',
            },
            keywords=None,
            space_tokens={'SPACE'},
            start_symbol_name='E',
            end_token_name='$END$',
            productions={
                'E': [
                    ('T', 'EE'),
                ],
                'EE': [
                    ('+', 'E', 'EE'),
                    None,
                ],
                'T': [
                    ('F', 'TT'),
                ],
                'TT': [
                    ('*', 'F', 'TT'),
                    None,
                ],
                'F': [
                    ('WORD', ),
                    ('(', 'E', ')'),
                ],
            },
            debug=False,
        )

        # parser.print_detailed_descr()

        x = parser.parse("a + b + c*x*y*z + d")
        x.cleanup()
        # x.printme()
