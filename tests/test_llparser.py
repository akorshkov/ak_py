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
        # x.printme()
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


class TestParsingClasslookingObj(unittest.TestCase):
    """Test parsing of class-like object."""

    def _make_test_parser(self, keep_symbols=None):
        # prepare the parser for tests
        return LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<COMMA>,)
            |(?P<BR_OPEN_CURL>\{)
            |(?P<BR_CLOSE_CURL>\})
            |(?P<COLON>:)
            |(?P<SEMI_COLON>;)
            """,
            synonyms={
                'COMMA': ',',
                'BR_OPEN_CURL': '{',
                'BR_CLOSE_CURL': '}',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'COLON': ':',
                'SEMI_COLON': ';',
            },
            keywords={
                ('WORD', 'class'): '$CLASS',
            },
            productions={
                'E': [
                    ('CLASSES_LIST', ),
                ],
                'CLASSES_LIST': [
                    ('CLASS', 'CLASSES_LIST'),
                    None,
                ],
                'CLASS': [
                    ('$CLASS', 'OBJ_NAME', 'OPT_PARENT', '{', 'CONTENTS', '}', ';'),
                ],
                'OPT_PARENT': [
                    (':', 'OBJ_NAME'),
                    None,
                ],
                'OBJ_NAME': [
                    ('WORD', ),
                ],
                'CONTENTS': [
                    ('WORD', ),
                ],
            },
            lists={
                'CLASSES_LIST': (None, ';', 'CLASSES_LIST', None),
            },
            keep_symbols=keep_symbols,
        )

    def test_parsing_text_of_class(self):
        """Test parsing of a primitive class-looking object."""

        parser = self._make_test_parser()

        x = parser.parse("class MyClass : Base { some };")
        self.assertIsInstance(x, TElement)
        self.assertEqual(x.name, 'E')
        self.assertEqual(('E', ), x.signature())
        self.assertIsInstance(x.value, list)
        self.assertEqual(len(x.value), 1)  # one class in source text

        c = x.value[0]
        self.assertEqual(c.get_path_val('OBJ_NAME'), 'MyClass')

    def test_parsking_keep_symbols(self):
        """Test prohibit to remove some nodes during cleanup."""

        parser = self._make_test_parser(keep_symbols={'CLASSES_LIST', })
        x = parser.parse("class MyClass : Base { some };")
        self.assertEqual(x.name, 'E')
        self.assertEqual(('E', 'CLASSES_LIST'), x.signature())

        classes_list = x.get_path_val('CLASSES_LIST')
        self.assertIsInstance(classes_list, list)
        self.assertIsInstance(classes_list[0], TElement)
        self.assertEqual(classes_list[0].name, 'CLASS')

    def test_get_methods(self):
        """Test TElement get methods."""
        parser = self._make_test_parser()

        x = parser.parse(
            "class MyClass : Base { some };"
            "class MyClass1 : Base1 { some1 };"
        )
        # x.printme()
        self.assertEqual(x.name, 'E')

        c0 = x.value[0]
        # c0 looks like this:
        #   CLASS:
        #    $CLASS: class
        #    OBJ_NAME: MyClass
        #    OPT_PARENT:
        #      :: :
        #      OBJ_NAME: Base
        #    {: {
        #    CONTENTS: some
        #    }: }
        #    ;: ;

        self.assertIsInstance(c0, TElement)
        self.assertEqual(c0.name, 'CLASS')

        opt_parent = c0.get('OPT_PARENT')
        self.assertIsInstance(opt_parent, TElement)
        self.assertFalse(opt_parent.is_leaf())

        base_name_elem = c0.get_path_elem('OPT_PARENT.OBJ_NAME')
        self.assertIsInstance(base_name_elem, TElement)
        self.assertEqual(base_name_elem.value, 'Base')

        base_name = c0.get_path_val('OPT_PARENT.OBJ_NAME')
        self.assertEqual(base_name, 'Base')

        # test non-existing paths
        self.assertIsNone(c0.get('BAD_CHILD'))
        self.assertIsNone(c0.get_path_elem('BAD_ELEM.PATH'))
        self.assertIsNone(c0.get_path_val('BAD_ELEM.PATH'))


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
        self.assertEqual(('E', 'SLAG', ), x.signature())
        self.assertEqual('aa', x.get_path_val('SLAG.WORD'))

        # 2. single '+'
        x = parser.parse("aa + bb")
        self.assertEqual(('E', 'SLAG', '+', 'E'), x.signature())

        # 3. single '*'
        x = parser.parse("aa * bb")
        self.assertEqual(('E', 'SLAG'), x.signature())

        x = x.get('SLAG')
        self.assertEqual(('SLAG', 'WORD', '*', 'SLAG'), x.signature())

    def test_multiple_operations(self):
        """parse expression with multiple aoprations"""
        parser = self._make_test_parser()
        # parser.print_detailed_descr()

        x = parser.parse("aa + bb * cc + dd")

        self.assertTrue(isinstance(x, TElement), f"{type(x)}")
        self.assertEqual(('E', 'SLAG', '+', 'E'), x.signature())

        first_slag = x.value[0]
        self.assertEqual(
            ('SLAG', 'WORD'), first_slag.signature(),
            f"the element:\n{first_slag}",
        )
        self.assertEqual('aa', first_slag.get_path_val('WORD'))

        second_slag = x.value[2]
        self.assertEqual(
            ('E', 'SLAG', '+', 'E'), second_slag.signature(),
            f"the element:\n{second_slag}",
        )

        self.assertEqual(
            ('SLAG', 'WORD', '*', 'SLAG'),
            second_slag.value[0].signature(),
            f"the element:\n{second_slag}",
        )

    def test_expression_with_braces(self):
        """Test more complex valid expression with braces"""
        parser = self._make_test_parser()
        x = parser.parse("(a) + ( b - c * d ) + ( x )")

        self.assertEqual(('E', 'SLAG', '+', 'E'), x.signature())

        first_slag = x.value[0]
        self.assertEqual(('SLAG', '(', 'E', ')'), first_slag.signature())

        second_slag = x.value[2]
        self.assertEqual(('E', 'SLAG', '+', 'E'), second_slag.signature())

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
            keep_symbols={'E'},
            lists={
                'LIST': ('[', ',', 'OPT_LIST', ']'),
            },
        )
        # parser.print_detailed_descr()

        x = parser.parse("[ a, b, c, d]")
        # x.printme()
        self.assertEqual(('E', ), x.signature())
        self.assertTrue(x.is_leaf(), f"it's not a tree node, so it's a leaf: {x}")
        self.assertEqual(4, len(x.value))

        x = parser.parse("[a, b, [d, e, f], c,]")
        # x.printme()
        self.assertEqual(('E', ), x.signature())
        self.assertEqual(4, len(x.value))
        self.assertEqual(x.value[0], "a")
        self.assertEqual(x.value[2], ["d", "e", "f"])

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
        # x.printme()
        self.assertEqual(('E', ), x.signature())


class TestCommentsStripper(unittest.TestCase):
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
            lists={
                'LIST': ('[', ',', 'OPT_LIST', ']'),
            },
        )

    def test_single_comment(self):
        """Text has single comment"""
        parser = self._make_test_parser()

        x = parser.parse("[a, b, /* c, d, */ e]")
        self.assertEqual(x.value, ['a', 'b', 'e'])

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
        self.assertEqual(x.value, ['a', 'b', 'e', 'f'])

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
        self.assertEqual(x.value, ['a', 'b', 'e', 'f'])

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
        self.assertEqual(x.value, ['a', 'b', 'e', 'f'])

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

    def _make_test_parser(self):
        # prepare the parser for tests
        return LLParser(
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

    def test_list_missing_values(self):
        """Test list with 'missing' values.

        For example [a, , b,].
        """
        parser = self._make_test_parser()

        x = parser.parse("[]")
        self.assertEqual(x.name, 'E', f"{x}")
        self.assertEqual(x.value, [])

        x = parser.parse("[a]")
        self.assertEqual(x.value, ["a"])

        x = parser.parse("[a, ]")
        self.assertEqual(x.value, ["a"])

        x = parser.parse("[a,, ]")
        self.assertEqual(x.value, ["a", None])

        x = parser.parse("[,]")
        self.assertEqual(x.value, [None])

        x = parser.parse("[,a,]")
        self.assertEqual(x.value, [None, "a"])


class TestOptionalLists(unittest.TestCase):
    """Test processing of elements which can expand to null or list"""

    _PARSER = LLParser(
        r"""
        (?P<SPACE>\s+)
        |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
        |(?P<NUMBER>[0-9]+)
        """,
        productions={
            'E': [
                ('LIST_WORDS', 'NUMBER'),
            ],
            'LIST_WORDS': [
                ('WORD', 'LIST_WORDS'),
                None,
            ]
        },
        lists={
            'LIST_WORDS': (None, None, 'LIST_WORDS', None),
        }
    )

    def test_not_empty_list(self):
        """just to make sure parser works correctly."""

        x = self._PARSER.parse("a b c 10")
        the_list = x.get_path_val('LIST_WORDS')
        self.assertIsInstance(the_list, list, f"parsed tree:\n{x}")
        self.assertEqual(3, len(the_list), f"parsed tree:\n{x}")

    def test_empty_list(self):
        """Test situation when the optional list is not present in source text."""

        x = self._PARSER.parse("10", do_cleanup=False)
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        self.assertIsInstance(list_tree_elem, TElement, f"parsed tree:\n{x}")
        # LIST_WORDS is nullable, it is exapnded to None, so, the list is not
        # present in source, so, the value is None
        self.assertIsNone(list_tree_elem.value, f"parsed tree:\n{x}")

        x = self._PARSER.parse("10")
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        # cleanup operation removes LIST_WORDS element because it's value is None
        self.assertIsNone(
            list_tree_elem,
            f"parsed tree:\n{x}\ntree element corresponding to list:"
            f"\n{list_tree_elem}"
        )


class TestOptionalListsWithBracers(unittest.TestCase):
    """Test processing of elemets which can expand to null or list.

    Test is similar to TestOptionalLists, but in this grammar the list is
    explicitely enclosed in bracers.
    """

    _PARSER = LLParser(
        r"""
        (?P<SPACE>\s+)
        |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
        |(?P<NUMBER>[0-9]+)
        |(?P<BR_OPEN>\[)
        |(?P<BR_CLOSE>\])
        """,
        synonyms={
            'BR_OPEN': '[',
            'BR_CLOSE': ']',
        },
        productions={
            'E': [
                ('LIST_WORDS', 'NUMBER'),
            ],
            'LIST_WORDS': [
                ('[', 'LIST_WORDS_TAIL', ']'),
                None,
            ],
            'LIST_WORDS_TAIL': [
                ('WORD', 'LIST_WORDS_TAIL'),
                None,
            ],
        },
        lists={
            'LIST_WORDS': ('[', None, 'LIST_WORDS_TAIL', ']'),
        }
    )

    def test_not_empty_list(self):
        """just to make sure parser works correctly."""

        x = self._PARSER.parse("[a b c] 10")
        the_list = x.get_path_val('LIST_WORDS')
        self.assertIsInstance(the_list, list, f"parsed tree:\n{x}")
        self.assertEqual(3, len(the_list), f"parsed tree:\n{x}")

    def test_missing_list(self):
        """The list is not present => element removed from result tree."""

        x = self._PARSER.parse("10", do_cleanup=False)
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        self.assertIsInstance(list_tree_elem, TElement, f"parsed tree:\n{x}")
        # LIST_WORDS is nullable, it is exapnded to None, so, the list is not
        # present in source, so, the value is None
        self.assertIsNone(list_tree_elem.value, f"parsed tree:\n{x}")

        x = self._PARSER.parse("10")
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        # cleanup operation removes LIST_WORDS element because it's value is None
        self.assertIsNone(
            list_tree_elem,
            f"parsed tree:\n{x}\ntree element corresponding to list:"
            f"\n{list_tree_elem}"
        )

    def test_empty_list(self):
        """The list is empty => element is still present in result."""

        x = self._PARSER.parse("[] 10")
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        self.assertIsInstance(list_tree_elem, TElement, f"parsed tree:\n{x}")
        self.assertIsInstance(list_tree_elem.value, list, f"parsed tree:\n{x}")
        self.assertEqual(0, len(list_tree_elem.value), f"parsed tree:\n{x}")


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
        self.assertEqual(x.name, 'E', x.signature())
        the_map = x.value[0]
        self.assertIsInstance(the_map, dict)
        self.assertEqual(the_map['a'], 'aa')

        self.assertEqual(the_map['x'][1], 'b1')

        self.assertEqual(the_map['y']['z']['r'], 'rr')

    def test_map_trailing_comma(self):
        """Test parsing of a map with trailing comma"""
        parser = self._make_test_parser()

        x = parser.parse("[{a: aa,}]")
        # x.printme()

        the_map = x.value[0]
        self.assertEqual({'a'}, the_map.keys())

        self.assertEqual(the_map['a'], 'aa')

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
        self.assertEqual("b", x.get_path_val("EE.E.T.F.WORD"))
