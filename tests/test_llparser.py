"""Test LL Parser"""

import os
import unittest

from ak import llparser
from ak.llparser import LLParser, _Tokenizer, TElement


#########################
# modify LLParser to print detailed debug info if 'LLP_DBG' env is set

if os.environ.get('LLP_DBG'):
    # print detailed description of the parser after creation
    _ORIG_INIT = LLParser.__init__
    def _hooked_init(self, *args, **kwargs):
        _ORIG_INIT(self, *args, **kwargs)
        self.print_detailed_descr()
    LLParser.__init__ = _hooked_init
    # print detailed description of parse process
    _ORIG_PARSE_MTD = LLParser.parse
    def _hooked_parse_mtd(self, *args, **kwargs):
        if 'debug' not in kwargs:
            return _ORIG_PARSE_MTD(self, *args, **kwargs, debug=True)
        return _ORIG_PARSE_MTD(self, *args, **kwargs)
    LLParser.parse = _hooked_parse_mtd


#########################
# tests

class TestParserTokenizer(unittest.TestCase):
    """Test tokenizer used by LLParser"""

    def _make_tokenizer(self):

        return _Tokenizer(
            r"""
            (?P<SPACE>\s+)
            |(?P<COMMENT_EOL>//.*)
            |(?P<COMMENT_ML>/\*)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |"(?P<DQ_STRING>[^"]*)"
            |'(?P<SQ_STRING>[^']*)'
            |(?P<PLUS>\+)
            |(?P<MINUS>-)
            |(?P<MULT>\*)
            |(?P<DIV>/)
            |(?P<BR_OPEN>\()
            |(?P<BR_CLOSE>\))
            """,
            keywords={
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
                'COMMENT_EOL': 'COMMENT',
                'COMMENT_ML': 'COMMENT',
            },
            span_matchers={
                'COMMENT_ML': r"(?P<END_COMMENT>(\*[^/]|[^*])*)\*/",
            },
        )

    def test_tokenizer(self):
        """Test tokenizer"""

        tokenizer = self._make_tokenizer()

        tokens = [
            t for t in tokenizer.tokenize(
            """
            aaa "bb" '+' - xx* '+ -' / () x86  \n \t     c

            c class // a + b
            """,
            src_name="test string")
            if t.name not in {'SPACE', 'COMMENT'}
        ]
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

        t = tokens[0]
        self.assertEqual(t.src_pos.coords, (2, 13))

        t = tokens[-2]  # the last 'class' keyword before comment
        self.assertEqual(t.src_pos.coords, (5, 15))

        # just to make sure that 'line', 'col' and 'coords' report same data
        self.assertEqual(t.src_pos.line, 5)
        self.assertEqual(t.src_pos.col, 15)

    def test_tokenize_text_with_comments(self):
        """Test misc combinations of comments."""

        tokenizer = self._make_tokenizer()

        tokens = list(tokenizer.tokenize(
            """
            "str0" // commented "strA"
            "str1" /* commented "strB" */ "str2"
            // "strC" /* who cares */ "strD"
            "str3"  /*
            still comment "strE" // who cares
            still comment "strF"
            "strG" /* who cares
            but here comment ends:*/"str4"
            """,
            src_name="test string")
        )

        tokens_values = [
            t.value for t in tokens
            if t.name not in {'SPACE', 'COMMENT'}
        ]
        self.assertEqual(
            ["str0", "str1", "str2", "str3", "str4", None],
            tokens_values)

        # make sure positions of tokens are not affected by comments
        tt_coords = {
            t.value: t.src_pos.coords for t in tokens if t.value is not None}
        self.assertEqual(tt_coords['str0'], (2, 13))
        self.assertEqual(tt_coords['str1'], (3, 13))
        self.assertEqual(tt_coords['str2'], (3, 43))
        self.assertEqual(tt_coords['str3'], (5, 13))
        self.assertEqual(tt_coords['str4'], (9, 37))


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

        self.assertEqual(x.src_pos.coords, (1, 1))

        word_elem = x.value[0]
        self.assertEqual(word_elem.name, 'WORD')
        self.assertEqual(word_elem.src_pos.coords, (1, 1))


class TestSquashing(unittest.TestCase):
    """Test squashing elements during TElement cleanup."""

    def _make_test_parser(self, c_productions, keep_symbols=None):
        return LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<SIGN_LESS><)
            |(?P<SIGN_MORE>>)
            """,
            synonyms={
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'SIGN_LESS': '<',
                'SIGN_MORE': '>',
            },
            productions={
                'E': [
                    ('A', ),
                ],
                'A': [
                    ('B', ),
                ],
                'B': [
                    ('C', ),
                ],
                # this production will be different in different tests
                'C': c_productions,
                # list-releated productions
                'LIST': [
                    ('[', 'LIST_TAIL', ']'),
                ],
                'LIST_TAIL': [
                    ('WORD', 'LIST_TAIL'),
                    None,
                ],
                # non-trivial production
                'OBJECT': [
                    ('<', 'WORD', '>'),
                ],
            },
            lists = {'LIST': ('[', None, 'LIST_TAIL', ']')},
            keep_symbols=keep_symbols,
        )

    def _make_test_parser_01(self, keep_symbols=None):
        return LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<DEC>@[a-zA-Z0-9_]*)
            |(?P<INT>[0-9]*)
            """,
            productions={
                'E': [
                    ('A', ),
                ],
                'A': [
                    ('B1', ),
                    ('B2', ),
                ],
                'B1': [
                    ('C1', ),
                ],
                'C1': [
                    ('WORD', ),
                ],
                'B2': [
                    ('C2', ),
                ],
                'C2': [
                    ('D2', ),
                ],
                'D2': [
                    ('E2', ),
                    ('E3', ),
                ],
                'E2': [
                    ('F2', ),
                ],
                'F2': [
                    ('INT', ),
                ],
                'E3': [
                    ('F3', ),
                ],
                'F3': [
                    ('DEC', ),
                ],
            },
            keep_symbols=keep_symbols,
        )

    @staticmethod
    def _get_telems_names_chain(t_elem):
        # it is supposed that t_elem is a root of a 'chain' part of the tree
        # (where each element has only one child)
        #
        # returns list containing names of elements and the value of last element:
        # ['E', 'A', 'B', 'C', the_value]
        result = []
        final_value = None
        loop_detector = set()
        while True:
            assert t_elem not in loop_detector
            loop_detector.add(t_elem)
            result.append(t_elem.name)
            if t_elem.is_leaf() or len(t_elem.value) != 1:
                final_value = t_elem.value
                break
            t_elem = t_elem.value[0]
            assert isinstance(t_elem, TElement), f"{type(t_elem)}: {t_elem}"

        return result, final_value

    def test_squash_chain_ending_terminal(self):
        """Test chain ending with a terminal."""

        parser = self._make_test_parser(c_productions=[('WORD', ), ])
        # parser.print_detailed_descr()

        # w/o cleanup we have a full chain of elements
        x = parser.parse("test_word", do_cleanup=False)
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'A', 'B', 'C', 'WORD'], 'test_word'))

        parser = self._make_test_parser(c_productions=[('WORD', ), ])

        x = parser.parse("test_word")
        # we have a chain of productions:
        # E: A: B: C: WORD: test_word
        # which is interpreted as "'E' is an alternative name of 'WORD'"
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E'], 'test_word'))

        # we want to keep symbol in the middle of the chain (symbol 'B').
        # So, chain ['E', 'A', 'B', 'C'] is squashed to ['E', 'B']
        # ('E' remains because it's the start symbol of production)
        parser = self._make_test_parser(
            c_productions=[('WORD', ), ], keep_symbols={'B'})
        x = parser.parse("test_word")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'B'], 'test_word'))

        # keep last symbol
        parser = self._make_test_parser(
            c_productions=[('WORD', ), ], keep_symbols={'WORD', })
        x = parser.parse("test_word")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'WORD'], 'test_word'))

        # keep several symbols
        parser = self._make_test_parser(
            c_productions=[('WORD', ), ], keep_symbols={'B', 'A'})
        x = parser.parse("test_word")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'A', 'B'], 'test_word'))

        # keep all symbols
        parser = self._make_test_parser(
            c_productions=[('WORD', ), ], keep_symbols={'E', 'B', 'A', 'C', 'WORD'})
        x = parser.parse("test_word")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'A', 'B', 'C', 'WORD'], 'test_word'))

    def test_squash_chain_ending_list(self):
        """Test chain ending with a list."""

        parser = self._make_test_parser(c_productions=[('LIST', ), ])

        x = parser.parse("[x1 x2]", do_cleanup=False)
        self.assertEqual(
            self._get_telems_names_chain(x)[0],
            ['E', 'A', 'B', 'C', 'LIST'])

        # we have a chain of productions:
        # E: A: B: C: LIST: ['x1', 'x2']
        # which is interpreted as "'E' is an alternative name of 'LIST'"
        x = parser.parse("[x1 x2]")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E'], ['x1', 'x2']))

    def test_squash_chain_ending_obj(self):
        """Test chain ending with a obj."""

        parser = self._make_test_parser(c_productions=[('OBJECT', ), ])
        # parser.print_detailed_descr()

        x = parser.parse("<x1>", do_cleanup=False)
        self.assertEqual(
            self._get_telems_names_chain(x)[0],
            ['E', 'A', 'B', 'C', 'OBJECT'])

        # we have a chain of productions:
        # E: A: B: C: OBJECT: TElement
        # which is interpreted as "'E' is an alternative name of 'OBJECT'"
        x = parser.parse("<x1>")
        self.assertEqual(
            self._get_telems_names_chain(x)[0],
            ['E'])

    def test_squash_notsquashable_chain(self):
        """Result tree is a chain, but squashing it is not possible """
        parser = self._make_test_parser_01()

        x = parser.parse("x1", do_cleanup=False)
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'A', 'B1', 'C1', 'WORD'], 'x1'))

        # even though the result tree is a chain, there are two
        # productions for 'A' symbol:
        # 'A' -> ('B1', )
        # 'A' -> ('B2', )
        # To preserve info about which production was used, symbol 'B1'
        # will not be cleaned up.

        parser = self._make_test_parser_01()
        x = parser.parse("x1")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'B1'], 'x1'))

    def test_squash_twice_notsquashable(self):
        """Result tree is a chain, but squashing it is not possible """
        parser = self._make_test_parser_01()

        x = parser.parse("@x1", do_cleanup=False)
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'A', 'B2', 'C2', 'D2', 'E3', 'F3', 'DEC'], '@x1'))

        # even though the result tree is a chain, there are two
        # symbols in this chain which have mupliple productions.
        # To preserve info that productions
        # 'A' -> ('B2', )
        # and
        # 'D2' -> ('E3', )
        # were actually used, these symbols ('B2' and 'E3')
        # will not be cleaned up.

        x = parser.parse("@x1")
        self.assertEqual(
            self._get_telems_names_chain(x),
            (['E', 'B2', 'E3'], '@x1'))


class TestSquashingInList(unittest.TestCase):
    """Test cleanup of list elements.

    During cleanup auxiliary symbols such as 'LIST_TAIL' or 'LIST_ELEMENT'
    shoud be squashed out.
    """

    def _make_test_parser(self, keep_symbols=None):
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<COMMA>,)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<TILDA>\~)
            |(?P<HAT>\^)
            |(?P<OR>\|)
            """,
            synonyms={
                'COMMA': ',',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'TILDA': '~',
                'HAT': '^',
                'OR': '|',
            },
            productions={
                'E': [
                    ('LIST',),
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
                    ('OBJECT_A', ),
                    ('OBJECT_B', ),
                ],
                'OBJECT_A': [
                    ('~', 'WORD', '~'),
                    ('^', 'WORD', '^'),
                ],
                'OBJECT_B': [
                    ('|', 'WORD', '|'),
                ],
            },
            keep_symbols=keep_symbols,
            lists={
                'LIST': ('[', ',', 'LIST_TAIL', ']'),
            },
        )
        return parser

    def test_squashing_in_list(self):
        """After cleanup 'LIST_TAIL' and 'LIST_ITEM' should not present in tree."""

        parser = self._make_test_parser()

        x = parser.parse("[a, ~x~, [], [i, ^y^, |z|]]")

        self.assertEqual(x.name, 'E', f"{x}")
        self.assertTrue(x.is_leaf(), f"{x}")

        the_list = x.value
        self.assertEqual(len(the_list), 4)

        self.assertEqual(the_list[0], 'a')

        self.assertIsInstance(the_list[1], TElement)
        # no auxiliary elements 'LIST_TAIL' and 'LIST_ITEM' should be there!
        self.assertEqual(the_list[1].name, 'OBJECT_A')

        self.assertEqual(the_list[2], [])

        self.assertIsInstance(the_list[3], list)
        inn_list = the_list[3]
        self.assertEqual(inn_list[0], 'i')
        self.assertIsInstance(inn_list[1], TElement)
        self.assertEqual(inn_list[1].name, 'OBJECT_A')

        self.assertEqual(inn_list[2].name, 'OBJECT_B')


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

        #                          1         2
        #                 123456789 123456789 123456789
        x = parser.parse("class MyClass : Base { some };")

        self.assertIsInstance(x, TElement)
        self.assertEqual(x.name, 'E')
        self.assertEqual(('E', ), x.signature())
        self.assertIsInstance(x.value, list)
        self.assertEqual(len(x.value), 1)  # one class in source text
        self.assertEqual(x.src_pos.coords, (1, 1))

        # tree element which corresponds to the whole class
        c = x.value[0]
        self.assertEqual(c.get_path_val('OBJ_NAME'), 'MyClass')
        self.assertEqual(c.src_pos.coords, (1, 1))

        # corresponds to text ": Base"
        opt_base_elem = c.get('OPT_PARENT')
        self.assertEqual(opt_base_elem.src_pos.coords, (1, 15))

        base_elem = opt_base_elem.get('OBJ_NAME')
        self.assertEqual(base_elem.value, "Base")
        self.assertEqual(base_elem.src_pos.coords, (1, 17))

        # contents elem: coresponds to text "some"
        cnt_elem = c.get('CONTENTS')
        self.assertEqual(cnt_elem.src_pos.coords, (1, 24))

    def test_parsing_keep_symbols(self):
        """Test prohibit to remove some nodes during cleanup."""

        parser = self._make_test_parser(keep_symbols={'CLASSES_LIST'})

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
            skip_tokens={'SPACE'},
            start_symbol_name='E',
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
        # x.printme()
        #E:
        #  SLAG:
        #    WORD: aa
        #    *: *
        #    SLAG:
        #      WORD: bb

        self.assertEqual(('E', 'SLAG'), x.signature())
        self.assertEqual(x.src_pos.coords, (1, 1))

        x = x.get('SLAG')
        self.assertEqual(('SLAG', 'WORD', '*', 'SLAG'), x.signature())
        self.assertEqual(x.src_pos.coords, (1, 1))

        self.assertEqual(
            x.value[2].src_pos.coords, (1, 6),
            "corresponds to source text 'bb'")

        self.assertEqual(
            x.value[2].get('WORD').src_pos.coords, (1, 6),
            "corresponds to source text 'bb'")


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
        #                 123456789 123456789
        x = parser.parse("(a) + ( b - c * d ) + ( x )")

        self.assertEqual(('E', 'SLAG', '+', 'E'), x.signature())

        first_slag = x.value[0]
        self.assertEqual(('SLAG', '(', 'E', ')'), first_slag.signature())

        second_slag = x.value[2]
        self.assertEqual(('E', 'SLAG', '+', 'E'), second_slag.signature())
        self.assertEqual(
            second_slag.src_pos.coords, (1, 7),
            "corresponds to text '( b - c * d )'")

    def test_bad_expression(self):
        # test parsing bad expressions
        parser = self._make_test_parser()

        with self.assertRaises(llparser.ParsingError) as exc:
            parser.parse("aa )")

        # reporting position of error is not very good.
        # but better than nothing!
        src_pos = exc.exception.src_pos
        self.assertEqual(src_pos.coords, (1, 1), "first line, first column")
        self.assertEqual("input text", src_pos.src_name)  # hardcoded string


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
            lists={
                'LIST': ('[', ',', 'OPT_LIST', ']'),
            },
        )
        # parser.print_detailed_descr()

        x = parser.parse("  [ a, b, c, d]")
        # x.printme()
        self.assertEqual(('E', ), x.signature())
        self.assertTrue(x.is_leaf(), f"it's not a tree node, so it's a leaf: {x}")
        self.assertEqual(4, len(x.value))
        self.assertEqual(x.src_pos.coords, (1, 3))

        #                 123456789 123456789
        x = parser.parse("[a, b, [d, e, f], c,]")
        # x.printme()
        self.assertEqual(('E', ), x.signature())
        self.assertEqual(4, len(x.value))
        self.assertEqual(x.value[0], "a")
        self.assertEqual(x.value[2], ["d", "e", "f"])
        self.assertEqual(x.src_pos.coords, (1, 1))

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
            |(?P<COMMENT_EOL>//.*)
            |(?P<COMMENT_ML>/\*)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<COMMA>,)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            """,
            synonyms={
                'COMMA': ',',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'COMMENT_EOL': 'COMMENT',
                'COMMENT_ML': 'COMMENT',
            },
            span_matchers={
                'COMMENT_ML': r"(?P<END_COMMENT>(\*[^/]|[^*])*)\*/",
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
            lists={
                'LIST': ('[', ',', 'OPT_LIST', ']'),
            },
        )

    def test_single_comment(self):
        """Text has single comment"""
        parser = self._make_test_parser()

        x = parser.parse("[a, b, /* c, d, */ e]")
        self.assertEqual(x.value, ['a', 'b', 'e'])

        # test empty comment
        x = parser.parse("[a, b,/**/c, d, e]")
        self.assertEqual(x.value, ['a', 'b', 'c', 'd', 'e'])

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
        self.assertIn("span is never closed", err_msg)
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

    @staticmethod
    def _make_test_parser():
        return LLParser(
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

        x = self._make_test_parser().parse("a b c 10")
        the_list = x.get_path_val('LIST_WORDS')
        self.assertIsInstance(the_list, list, f"parsed tree:\n{x}")
        self.assertEqual(3, len(the_list), f"parsed tree:\n{x}")

    def test_empty_list(self):
        """Test situation when the optional list is not present in source text."""

        x = self._make_test_parser().parse("10", do_cleanup=False)
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        self.assertIsInstance(list_tree_elem, TElement, f"parsed tree:\n{x}")
        # LIST_WORDS is nullable, it is exapnded to None, so, the list is not
        # present in source, so, the value is None
        self.assertIsNone(list_tree_elem.value, f"parsed tree:\n{x}")

        x = self._make_test_parser().parse("10")
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        # LIST_WORDS has no explicit open/close tokens. In this case it is more
        # convenient to have it's value not None, but []
        self.assertEqual(list_tree_elem.value, [])


class TestOptionalListsWithBracers(unittest.TestCase):
    """Test processing of elemets which can expand to null or list.

    Test is similar to TestOptionalLists, but in this grammar the list is
    explicitely enclosed in bracers.
    """

    @staticmethod
    def _make_test_parser():
        return LLParser(
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

        x = self._make_test_parser().parse("[a b c] 10")
        the_list = x.get_path_val('LIST_WORDS')
        self.assertIsInstance(the_list, list, f"parsed tree:\n{x}")
        self.assertEqual(3, len(the_list), f"parsed tree:\n{x}")

    def test_missing_list(self):
        """The list is not present => element removed from result tree."""

        x = self._make_test_parser().parse("10", do_cleanup=False)
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        self.assertIsInstance(list_tree_elem, TElement, f"parsed tree:\n{x}")
        # LIST_WORDS is nullable, it is exapnded to None, so, the list is not
        # present in source, so, the value is None
        self.assertIsNone(list_tree_elem.value, f"parsed tree:\n{x}")

        x = self._make_test_parser().parse("10")
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        # cleanup operation removes LIST_WORDS element because it's value is None
        self.assertIsNone(
            list_tree_elem,
            f"parsed tree:\n{x}\ntree element corresponding to list:"
            f"\n{list_tree_elem}"
        )

    def test_empty_list(self):
        """The list is empty => element is still present in result."""

        x = self._make_test_parser().parse("[] 10")
        list_tree_elem = x.get_path_elem('LIST_WORDS')
        self.assertIsInstance(list_tree_elem, TElement, f"parsed tree:\n{x}")
        self.assertIsInstance(list_tree_elem.value, list, f"parsed tree:\n{x}")
        self.assertEqual(0, len(list_tree_elem.value), f"parsed tree:\n{x}")


class TestMapGrammar(unittest.TestCase):
    """Test grammar of map"""

    def _make_test_parser(self, keep_symbols=None) -> LLParser:
        # prepare the parser for tests
        return LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<COMMA>,)
            |(?P<SIGN_LESS><)
            |(?P<SIGN_MORE>>)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<BR_OPEN_CURL>\{)
            |(?P<BR_CLOSE_CURL>\})
            |(?P<COLON>:)
            """,
            synonyms={
                'COMMA': ',',
                'SIGN_LESS': '<',
                'SIGN_MORE': '>',
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'BR_OPEN_CURL': '{',
                'BR_CLOSE_CURL': '}',
                'COLON': ':',
            },
            productions={
                'E': [
                    ('VALUE', ),
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
                    ('OBJECT', ),
                ],
                'OBJECT': [
                    ('<', 'VALUE', '>'),
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
            keep_symbols=keep_symbols,
        )

    def test_simple_map(self):
        """Test grammar: just make sure grammar works ok."""
        parser = self._make_test_parser()

        x = parser.parse("{}")
        self.assertIsInstance(x, TElement)
        self.assertEqual(x.name, 'E', x.signature())

        #E:
        #  MAP: {}

        the_map = x.get_path_val('MAP')
        self.assertEqual(the_map, {})

    def test_simple_map_in_map(self):
        """Test combination of lists and maps."""
        parser = self._make_test_parser()

        x = parser.parse("{a:{}, b:[]}")
        self.assertIsInstance(x, TElement)
        self.assertEqual(x.name, 'E', x.signature())

        expected_descr = (
            "E:",
            "  MAP: {",
            "    b: []",
            "    a: {}",
            "  }",
        )
        actual_descr = tuple(f"{x}".split('\n'))
        self.assertEqual(expected_descr, actual_descr)

    def test_list_containing_obj(self):
        """Text list containing not a trivial object."""
        parser = self._make_test_parser()

        x = parser.parse("[a1, <x1>]")
        self.assertIsInstance(x, TElement)

        #E:
        #  LIST: [
        #    a1
        #    OBJECT:
        #      <: <
        #      WORD: x1
        #      >: >
        #  ]

        list_elem = x.get_path_elem('LIST')

        self.assertTrue(list_elem.is_leaf())
        self.assertEqual(list_elem.value[0], 'a1')
        the_obj = list_elem.value[1]
        self.assertIsInstance(the_obj, TElement)
        self.assertEqual(the_obj.signature(), ('OBJECT', '<', 'WORD', '>'))

    def test_complex_lists_maps_object(self):
        """Text complex lists/maps object."""
        parser = self._make_test_parser()

        x = parser.parse(
            """
            [
              a, [], {}, <x1>,
              {
                k1: <{k11: v11, k12: {}}>,
                k2: v2,
                k3: [v31, v31, v33],
                k4: {},
                k5: {
                  k11: [],
                  k12: {k112: v112},
                }
              }
            ]
            """,
        )
        self.assertIsInstance(x, TElement)

        # probably less strict test is required here
        expected_descr = (
            "E:",
            "  LIST: [",
            "    a",
            "    []",
            "    {}",
            "    OBJECT:",
            "      <: <",
            "      WORD: x1",
            "      >: >",
            "    {",
            "      k5: {",
            "        k12: {",
            "          k112: v112",
            "        }",
            "        k11: []",
            "      }",
            "      k4: {}",
            "      k3: [",
            "        v31",
            "        v31",
            "        v33",
            "      ]",
            "      k2: v2",
            "      k1: OBJECT:",
            "        <: <",
            "        MAP: {",
            "          k12: {}",
            "          k11: v11",
            "        }",
            "        >: >",
            "    }",
            "  ]",
        )
        actual_descr = f"{x}"
        actual_descr_lines = set(actual_descr.split('\n'))
        missing_lines = [
            line for line in expected_descr
            if line not in actual_descr_lines
        ]
        if missing_lines:
            self.fail(
                f"line '{missing_lines[0]}' not found in {actual_descr_lines}.\n"
                f"actual_descr:\n{actual_descr}")

    def test_map_in_list(self):
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
        the_map = x.get_path_val('LIST')[0]
        self.assertIsInstance(the_map, dict)
        self.assertEqual(the_map['a'], 'aa')

        self.assertEqual(the_map['x'][1], 'b1')

        self.assertEqual(the_map['y']['z']['r'], 'rr')

    def test_map_trailing_comma(self):
        """Test parsing of a map with trailing comma"""
        parser = self._make_test_parser()

        x = parser.parse("[{a: aa,}]")

        the_map = x.get_path_val('LIST')[0]
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


class TestSequenceProductions(unittest.TestCase):
    """'ProdSequence' is a pseudo-production which matches sequence of elements."""

    def test_sequence_production(self):
        """Test sequence pseudo-production."""
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<SEMI_COLON>;)
            """,
            synonyms={
                'SEMI_COLON': ';',
            },
            keywords={
                ('WORD', 'val_k'): 'Val_k',
                ('WORD', 'val_l'): 'Val_l',
                ('WORD', 'val_m'): 'Val_m',
                ('WORD', 'val_n'): 'Val_n',
                ('WORD', 'val_p'): 'Val_p',
            },
            productions={
                'E': [
                    ('STATEMENT', ),
                ],
                'STATEMENT': [
                    ('SEQUENCE', ';'),
                ],
                'SEQUENCE': LLParser.ProdSequence(
                    ('Val_k', ),
                    ('L', ),
                ),
                'L': [
                    ('Val_l', ),
                ],
            },
        )

        x = parser.parse("val_k val_l val_l val_l val_l;")

        seq_elem = x.get_path_elem('SEQUENCE')
        self.assertTrue(seq_elem.is_leaf())

        seq = seq_elem.value
        self.assertIsInstance(seq, list, f"{seq=}")
        self.assertEqual(len(seq), 5, f"{seq=}")

        seq_elems_names = [x.name for x in seq]

        self.assertEqual(seq_elems_names, ['Val_k', 'L', 'L', 'L', 'L'], f"{seq=}")


class TestBulkProductions(unittest.TestCase):
    """Test 'AnyTokenExcept' pseudo-production."""

    def test_anyexcept_production_in_list(self):
        """Test useing 'AnyTokenExcept' in list."""
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<SIGN_LESS><)
            |(?P<SIGN_MORE>>)
            |(?P<SEMI_COLON>;)
            """,
            synonyms={
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'SIGN_LESS': '<',
                'SIGN_MORE': '>',
                'SEMI_COLON': ';',
            },
            keywords={
                ('WORD', 'k'): 'Val_k',
                ('WORD', 'l'): 'Val_l',
                ('WORD', 'm'): 'Val_m',
                ('WORD', 'n'): 'Val_n',
                ('WORD', 'p'): 'Val_p',
            },
            productions={
                'E': [
                    ('LIST', ),
                ],
                'LIST': [
                    ('[', 'LIST_TAIL', ']'),
                ],
                'LIST_TAIL': [
                    ('LIST_ITEM', 'LIST_TAIL'),
                    None,
                ],
                'LIST_ITEM': [
                    LLParser.AnyTokenExcept('Val_k', '<'),
                    ('K', ),
                ],
                'K': [
                    ('<', 'Val_k', '>'),
                ],
            },
            lists = {'LIST': ('[', None, 'LIST_TAIL', ']')},
        )

        # 01 parse list of tokens
        x = parser.parse("[ l l m n]")

        self.assertTrue(x.is_leaf(), f"{x}")
        self.assertEqual(x.value, ['l', 'l', 'm', 'n'], f"{x}")

        # 02 parse list of tokens and complex symbols
        x = parser.parse("[ l <k >]")
        self.assertEqual(x.value[0], 'l', f"{x}")
        self.assertIsInstance(x.value[1], TElement, f"{x}")

        # 03 parse list which contains prohibited token
        with self.assertRaises(llparser.ParsingError):
            # 'Val_k' is explicitely excluded from set of applicable tokens
            parser.parse("[ k ]")

    def test_anyexcept_production_is_sequence(self):
        """Test useing 'AnyTokenExcept' in sequence."""
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<BR_OPEN>\[)
            |(?P<BR_CLOSE>\])
            |(?P<SIGN_LESS><)
            |(?P<SIGN_MORE>>)
            |(?P<SEMI_COLON>;)
            """,
            synonyms={
                'BR_OPEN': '[',
                'BR_CLOSE': ']',
                'SIGN_LESS': '<',
                'SIGN_MORE': '>',
                'SEMI_COLON': ';',
            },
            keywords={
                ('WORD', 'k'): 'Val_k',
                ('WORD', 'l'): 'Val_l',
                ('WORD', 'm'): 'Val_m',
                ('WORD', 'n'): 'Val_n',
                ('WORD', 'p'): 'Val_p',
            },
            productions={
                'E': [
                    ('SEQUENCE', ';'),
                ],
                'SEQUENCE': LLParser.ProdSequence(
                    ('Val_k', ),
                    LLParser.AnyTokenExcept('Val_k', 'Val_l'),
                ),
            },
        )

        # 01. successull parse
        # 'k' may be present in sequence because even though it's prohibited in
        # AnyTokenExcept, there is an explicit production: ('Val_k', )
        x = parser.parse("m n k;")

        seq = x.get_path_val('SEQUENCE')
        self.assertIsInstance(seq, list)
        self.assertEqual(len(seq), 3, f"{x}")

        # 02. fail scenario
        # should fail because 'l' is not allowed in sequence
        with self.assertRaises(llparser.ParsingError):
            parser.parse("m n l;")


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
            skip_tokens={'SPACE'},
            start_symbol_name='E',
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


class TestAmbiguousGrammar(unittest.TestCase):
    """Test grammars, which are not ll1.

    Some may be factored to ll1, others - not.
    """

    def test_nonll1_grammar_01(self):
        """Grammar is not ll1, but still should work."""

        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            """,
            keywords={
                ('WORD', 'val_k'): 'val_k',
                ('WORD', 'val_l'): 'val_l',
                ('WORD', 'val_m'): 'val_m',
                ('WORD', 'val_n'): 'val_n',
                ('WORD', 'val_p'): 'val_p',
            },
            productions={
                'E': [
                    ('A', ),
                ],
                'A': [
                    ('val_k', 'val_m'),
                    ('val_k', 'val_n'),
                ],
            },
        )

        # It's not possible to guess which production will be used for
        # symbol 'A' and next token 'val_k'.
        # At the time this test is created grammar factorization is not implememted,
        # but still parsing process should be able to recover from error and parse
        # both variants

        x = parser.parse("val_k val_m", do_cleanup=False)
        self.assertEqual(x.get_path_val("A.val_m"), "val_m")
        self.assertIsNone(x.get_path_val("A.val_n"))

        x = parser.parse("val_k val_n", do_cleanup=False)
        self.assertIsNone(x.get_path_val("A.val_m"))
        self.assertEqual(x.get_path_val("A.val_n"), "val_n")

    def test_nonll1_grammar_02(self):
        """Grammar is not ll1, but still should work."""
        # test is quite similar to test_nonll1_grammar_01, but grammar is
        # a little bit more complex

        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            """,
            keywords={
                ('WORD', 'val_k'): 'val_k',
                ('WORD', 'val_l'): 'val_l',
                ('WORD', 'val_m'): 'val_m',
                ('WORD', 'val_n'): 'val_n',
                ('WORD', 'val_p'): 'val_p',
            },
            productions={
                'E': [
                    ('A', ),
                ],
                'A': [
                    ('K', 'M'),
                    ('K', 'N'),
                ],
                'K': [
                    ('val_k', ),
                ],
                'M': [
                    ('val_m', ),
                ],
                'N': [
                    ('val_n', ),
                ],
            },
        )

        x = parser.parse("val_k val_m", do_cleanup=False)
        self.assertEqual(x.get_path_val("A.M.val_m"), "val_m")
        self.assertIsNone(x.get_path_val("A.N.val_n"))

        x = parser.parse("val_k val_n", do_cleanup=False)
        self.assertIsNone(x.get_path_val("A.M.val_m"))
        self.assertEqual(x.get_path_val("A.N.val_n"), "val_n")

    def test_nonll1_grammar_03(self):
        """Grammar is not ll1. More complicated case."""
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            """,
            keywords={
                ('WORD', 'k'): 'val_k',
                ('WORD', 'l'): 'val_l',
                ('WORD', 'm'): 'val_m',
                ('WORD', 'n'): 'val_n',
                ('WORD', 'FIN'): 'FIN',
            },
            productions={
                'E': [
                    ('A', ),
                ],
                'A': [
                    ('B', 'FIN'),
                ],
                'B': [
                    ('val_k', 'val_l'),             # production P1
                    ('val_k', 'val_l', 'val_m'),    # production P2
                ],
            },
        )

        # the following text can be parsed if production P2 is used.
        # but during parse process production P1 is tried first and matches.
        #
        # Problem can be fixed by placing P2 before P1.
        #
        # Parsing should not fail after automatic grammar factorization is
        # implemented.

        self.assertTrue(not parser.is_ambiguous())

        x = parser.parse("k l m FIN", do_cleanup=False)
        words = [t_elem.value for t_elem in x.get_path_val('A.B')]
        self.assertEqual(words, ['k', 'l', 'm'])

    def test_nonll1_grammar_04(self):
        """Grammar is not ll1. More complicated case."""
        parser = LLParser(
            r"""
            (?P<SPACE>\s+)
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            """,
            keywords={
                ('WORD', 'k'): 'val_k',
                ('WORD', 'l'): 'val_l',
                ('WORD', 'm'): 'val_m',
                ('WORD', 'n'): 'val_n',
                ('WORD', 'FIN'): 'FIN',
            },
            productions={
                'E': [
                    ('A', ),
                ],
                'A': [
                    ('B', 'FIN'),
                ],
                'B': [
                    ('val_k', 'val_l', 'val_m'),
                    ('val_k', 'val_l'),
                    ('val_k', 'val_n'),
                    ('val_m', 'val_k', 'val_l'),
                    ('val_m', 'val_k', 'val_m'),
                ],
            },
        )

        words = lambda root_t_elem: [
            t_elem.value for t_elem in root_t_elem.get_path_val('B')]

        self.assertTrue(not parser.is_ambiguous())
        x = parser.parse("k l FIN")
        self.assertEqual(words(x), ['k', 'l'])

        x = parser.parse("k n FIN")
        self.assertEqual(words(x), ['k', 'n'])

        x = parser.parse("k l m FIN")
        self.assertEqual(words(x), ['k', 'l', 'm'])

        x = parser.parse("m k l FIN")
        self.assertEqual(words(x), ['m', 'k', 'l'])

        x = parser.parse("m k m FIN")
        self.assertEqual(words(x), ['m', 'k', 'm'])
