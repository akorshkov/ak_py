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

    def _make_test_parser(self):
        # make the parser for tests

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
        )
        return parser

    def test_simple_operations(self):
        """Parse very simple expressions."""
        parser = self._make_test_parser()

        # 1. one word, cleanup later
        x = parser.parse("aa", do_cleanup=False)
        self.assertTrue(isinstance(x, TElement), f"{type(x)}")
        self.assertEqual(('E', 'SLAG'), x.signature())
        self.assertEqual(('SLAG', 'WORD'), x.value[0].signature())
        self.assertEqual("aa", x.value[0].value[0].value)

        parser.cleanup(x)
        self.assertTrue(isinstance(x, TElement), f"{type(x)}")
        self.assertEqual(('WORD', ), x.signature())
        self.assertEqual('aa', x.value)

        # 2. single '+'
        x = parser.parse("aa + bb")
        self.assertEqual(('E', 'WORD', '+', 'WORD'), x.signature())

        # 3. single '*'
        x = parser.parse("aa * bb")
        self.assertEqual(('SLAG', 'WORD', '*', 'WORD'), x.signature())

    def test_multiple_operations(self):
        """parse expression with multiple aoprations"""
        parser = self._make_test_parser()
        # parser.print_detailed_descr()

        x = parser.parse("aa + bb * cc + dd")

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
        # x.printme()
        self.assertEqual(('E', 'SLAG', '+', 'E'), x.signature())

        first_slag = x.value[0]
        self.assertEqual(('SLAG', '(', 'WORD', ')'), first_slag.signature())

        second_slag = x.value[2]
        self.assertEqual(('E', 'SLAG', '+', 'SLAG'), second_slag.signature())

    def test_bad_expression(self):
        # test parsing bad expressions
        parser = self._make_test_parser()

        with self.assertRaises(llparser.ParsingError):
            parser.parse("aa )")


class TestListParsers(unittest.TestCase):
    """Test misc parsers of list."""

    def test_list_parser_01(self):
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
                    ('[', 'ITEM', 'OPT_LIST', ']'),
                ],
                'OPT_LIST': [
                    (',', 'ITEM', 'OPT_LIST'),
                    (',', ),
                    None,
                ],
                'ITEM': [
                    ('WORD', ),
                    ('LIST', ),
                ],
            },
            keep_symbols={'E', 'LIST'},
            lists={
                'LIST': ('[', ',', 'OPT_LIST', ']'),
            },
        )
        # parser.print_detailed_descr()

        x = parser.parse("[ a, b, c, d]")
        self.assertEqual(('E', 'LIST'), x.signature())
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD', 'WORD'),
            x.value[0].signature())

        x = parser.parse("[a, b, [d, e, f], c,]")
        # x.printme()
        self.assertEqual(('E', 'LIST'), x.signature())
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'LIST', 'WORD'),
            x.value[0].signature())

        # test TElement.get method
        list_elem = x.get('LIST')
        self.assertIs(list_elem, x.value[0])

        child_list = list_elem.get('LIST')
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD'),
            child_list.signature())

        with self.assertRaises(ValueError) as exc:
            child_list.get('WORD')

        err_msg = str(exc.exception)
        self.assertIn("has 3 child elements", err_msg)
        self.assertIn("'WORD'", err_msg)

        # test TElement.get_path_val method
        inner_elem = x.get_path_elem("LIST.LIST")
        self.assertIsInstance(inner_elem, TElement)

        inner_list = x.get_path_val("LIST.LIST")
        self.assertIsInstance(inner_list, list)
        self.assertEqual(3, len(inner_list))

        self.assertIs(inner_list, inner_elem.value)

        missing_elem = x.get_path_elem("LIST.E")
        self.assertIsNone(missing_elem)

        missing_val = x.get_path_val("LIST.E")
        self.assertIsNone(missing_val)

    def test_list_parser_02(self):
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
                    ('LIST', ),
                ],
                'LIST': [
                    ('[', 'LIST_TAIL', ']'),
                ],
                'LIST_TAIL': [
                    ('LIST_ITEM', ',', 'LIST_TAIL'),
                    ('LIST_ITEM', ),
                    None,
                ],
                'LIST_ITEM': [
                    ('WORD', ),
                    ('LIST', ),
                ],
            },
            lists = {'LIST': ('[', ',', 'LIST_TAIL', ']')},
        )
        # parser.print_detailed_descr()
        x = parser.parse("[ a, b, c, d]")
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD', 'WORD'),
            x.signature())


class TextCommentsStripper(unittest.TestCase):
    """Text comments stripper."""

    def _make_test_parser(self):
        # prepare the parser for tests
        return LLParser(
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
            comments=[
                "//",
                ('/*', '*/'),
            ],
            productions={
                'E': [
                    ('LIST',),
                ],
                'LIST': [
                    ('[', 'ITEM', 'OPT_LIST', ']'),
                ],
                'OPT_LIST': [
                    (',', 'ITEM', 'OPT_LIST'),
                    (',', ),
                    None,
                ],
                'ITEM': [
                    ('WORD', ),
                    ('LIST', ),
                ],
            },
            keep_symbols={'E', 'LIST'},
            lists={
                'LIST': ('[', ',', 'OPT_LIST', ']'),
            },
        )

    def test_single_comment(self):
        """Text has single comment"""
        parser = self._make_test_parser()

        x = parser.parse("[a, b, /* c, d, */ e]")
        self.assertEqual(('E', 'LIST'), x.signature())
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD'),
            x.value[0].signature())

    def test_single_oneline_comment(self):
        """Text has single comment"""
        parser = self._make_test_parser()

        x = parser.parse(
            """
            [a,
            b, // x, y
            // c, d,
            e, f]// more comment
            """
        )
        self.assertEqual(('E', 'LIST'), x.signature())
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD', 'WORD'),
            x.value[0].signature())

    def test_multiline_comment(self):
        """Test multi-line comment."""
        parser = self._make_test_parser()
        x = parser.parse(
            """
            [a,
            b, /* x, y
            */ e, f]
            """
        )
        self.assertEqual(('E', 'LIST'), x.signature())
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD', 'WORD'),
            x.value[0].signature())

    def test_multiple_comments(self):
        """Text has multiple comments of different types."""
        parser = self._make_test_parser()

        x = parser.parse(
            """
/*some ;; text/* more text */ [ // no text
a, b, /* c, d, */ e, /**/// omg
f /* g, h
    */ ]//comment
            """
        )
        self.assertEqual(('E', 'LIST'), x.signature())
        self.assertEqual(
            ('LIST', 'WORD', 'WORD', 'WORD', 'WORD'),
            x.value[0].signature())

    def test_not_closed_comment(self):
        """Test parsing invalid text: comment not closed."""
        parser = self._make_test_parser()

        with self.assertRaises(llparser.LexicalError) as exc:
            parser.parse(
                """[
                a, /* b, c
                ]
                """
            )

        err_msg = str(exc.exception)
        self.assertIn("comment is never closed", err_msg)
        self.assertIn("(2, 19)", err_msg)


class TestListWithNoneValues(unittest.TestCase):
    """Test list which may contain None values."""

    def test_list_missing_values(self):
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<NUMBER>[0-9]+)
            |(?P<COMMA>,)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<AT_SYMBOL>@)
            |(?P<EQUAL>=)
            |(?P<COLON>:)
            """,
            synonyms={
                'COMMA': ',',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
            },
            productions={
                'E': [
                    ('LIST_ITEMS', ),
                ],
                'LIST_ITEMS': [
                    ('[', 'LIST_ITEMS_TAIL', ']'),
                ],
                'LIST_ITEMS_TAIL': [
                    ('LIST_ITEM', ',', 'LIST_ITEMS_TAIL'),
                    ('LIST_ITEM', ),
                    None,
                ],
                'LIST_ITEM': [
                    ('WORD', ),
                    None,
                ],
            },
            lists={
                'LIST_ITEMS': ('[', ',', 'LIST_ITEMS_TAIL', ']'),
            },
        )
        x = parser.parse("[]")
        self.assertEqual(("LIST_ITEMS", ), x.signature(), f"{x}")

        x = parser.parse("[a]")
        self.assertEqual(("LIST_ITEMS", "WORD"), x.signature())

        x = parser.parse("[a, ]")
        self.assertEqual(("LIST_ITEMS", "WORD"), x.signature())

        x = parser.parse("[a,, ]")
        self.assertEqual(("LIST_ITEMS", "WORD", None), x.signature())

        x = parser.parse("[,]")
        self.assertEqual(("LIST_ITEMS", None), x.signature())

        x = parser.parse("[,a,]")
        self.assertEqual(("LIST_ITEMS", None, "WORD"), x.signature())


class TestMapGrammar(unittest.TestCase):
    """Test grammar of map"""

    def _make_test_parser(self):
        # prepare the parser for tests
        return LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<COMMA>,)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<BR_OPEN_CURL>\{)
            |(?P<BR_CLOSE_CURL>\})
            |(?P<COLON>:)
            """,
            synonyms={
                'COMMA': ',',
                'BR_OPEN_CURL': '{',
                'BR_CLOSE_CURL': '}',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'COLON': ':',
            },
            productions={
                'E': [
                    ('LIST', ),
                ],
                'LIST': [
                    ('[', 'LIST_ITEMS_TAIL', ']'),
                ],
                'LIST_ITEMS_TAIL': [
                    ('LIST_ITEM', ',', 'LIST_ITEMS_TAIL'),
                    ('LIST_ITEM', ),
                    None,
                ],
                'LIST_ITEM': [
                    ('VALUE', ),
                    None,
                ],
                'VALUE': [
                    ('WORD', ),
                    ('LIST', ),
                    ('MAP', ),
                ],
                'MAP': [
                    ('{', 'MAP_ELEMENTS', '}'),
                ],
                'MAP_ELEMENTS': [
                    ('MAP_ELEMENT', ',', 'MAP_ELEMENTS'),
                    ('MAP_ELEMENT', ),
                    None,
                ],
                'MAP_ELEMENT': [
                    ('WORD', ':', 'VALUE'),
                ],
            },
            lists={
                'LIST': ('[', ',', 'LIST_ITEMS_TAIL', ']'),
            },
            maps={
                'MAP': ('{', 'MAP_ELEMENTS', ',', 'MAP_ELEMENT', ':', '}'),
            },
        )

    def test_map_grammar(self):
        """Test grammar of map"""
        parser = self._make_test_parser()

        x = parser.parse(
            """[
            {
                a:aa, b: bb, c: cc, x: [a1, b1, c1], d: dd,
                y: {q: qq, z: {r: rr}}
            }]
            """)
        self.assertEqual(('LIST', 'MAP'), x.signature())
        the_map = x.value[0]
        self.assertEqual(('MAP', ), the_map.signature())

    def test_map_trailing_comma(self):
        """Test parsing of a map with trailing comma"""
        parser = self._make_test_parser()

        x = parser.parse("[{a: aa,}]")

        the_map = x.value[0].value
        self.assertEqual({'a'}, the_map.keys())

        val = the_map['a']
        self.assertIsInstance(val, TElement)
        self.assertEqual('aa', val.value)

    def test_telements_clone(self):
        """Test TElement helper methods"""
        parser = self._make_test_parser()

        x = parser.parse(
            """[
            {
                a:aa, b: bb, c: cc, x: [a1, b1, c1], d: dd,
                y: {q: qq, z: {r: rr}}
            }]
            """,
            do_cleanup=False,
        )

        orig_x_descr = str(x)
        cloned_x = x.clone()
        clone_x_descr = str(cloned_x)
        self.assertEqual(orig_x_descr, clone_x_descr)

        parser.cleanup(x)
        # make sure cleanup of the tree does not affect the clone
        new_clone_descr = str(cloned_x)
        self.assertEqual(clone_x_descr, new_clone_descr)

        cleanuped = str(x)
        self.assertNotEqual(orig_x_descr, cleanuped)


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


class TestSimpleParserWithNullProductions(unittest.TestCase):
    """Test very primitive parser with nullable productions."""

    def test_parser(self):
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            """,
            productions={
                'E': [
                    ('WORD', 'OPT_WORD'),
                ],
                'OPT_WORD': [
                    ('WORD', ),
                    None,
                ],
            },
            keep_symbols={'E'},
        )

        x = parser.parse("aaa", do_cleanup=False)
        self.assertEqual(
            ('E', 'WORD', 'OPT_WORD'), x.signature(),
            f"subtree is:\n{x}",
        )
        opt_word_elem = x.get("OPT_WORD")
        self.assertIsInstance(opt_word_elem, TElement)
        self.assertIsNone(opt_word_elem.value)

        x = parser.parse("aaa")
        self.assertEqual(
            ('E', 'WORD'), x.signature(),
            f"subtree is:\n{x}",
        )


class TestMathParserWithNullProductions(unittest.TestCase):
    """Test arithmetic parser with null productions"""

    def test_math_parser_null_productins(self):
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
        )

        x = parser.parse("a + b + c*x*y*z + d")
        # x.printme()
        self.assertEqual("E", x.name)
        self.assertEqual("b", x.get_path_val("EE.E.WORD"))
