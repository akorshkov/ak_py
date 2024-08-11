"""LL parser with some ambiguities handling.

Main difference from LL1 parser is that it allowes ambiguities.

- LLParser: the parser. Transforms text into tree of TElement objects.
- TElement: element of the tree created as a result of parsing
- ListProds: template of production rules, which can be used to parse lists
- MapProds: template of production rules, which can be used to parse maps
- ProdSequence: template of productin rules for "sequence of given symbols"
- AnyTokenExcept: helper used to create production rules for "any teminal
    symbols, except specified ones"
- StdCleanuper: used by LLParser by default for post-processing parsed TElement tree.
"""

# More detailed description and example:
#
# 1. LLParser allowes ambiguities. That means that
# parsing table may contain several matching productions for a pair:
# (SYMBOL, next_token) -> (A, B, C)
#                         (X, Y, Z)
# If matching process fails for the first production, parsing process will
# roll back and next production will be attempted. First successfully
# matched production will be used.
#
# So, it is possible to use following productions for symbol 'A':
# A: [
#     (X, Y, Z),
#     (X, Y),
# ]
#
# 2. LLParser automatically uses factorization to transform given grammar into
# equivalent, but more efficient one. If there are several
# productions with same prefix, grammar will be automatically transformed:
# A: [                  =>  A: [                  A__S00: [
#     (X, Y, A, B),     =>      (X, Y, A__S00),       (A, B),
#     (X, Y, C, D),     =>  ]                         (C, D),
# ]                                               ]
# In some cases this transformation may remove ambiguities.
#
#
# Example of usage:
#
# parser = LLParser(
#     r'''
#     (?P<SPACE>\s+)
#     |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
#     |(?P<NUMBER>[0-9]+)
#     |(?P<BR_OPEN>\[)
#     |(?P<BR_CLOSE>\])
#     ''',
#     synonyms={
#         'BR_OPEN': '[',
#         'BR_CLOSE': ']',
#     },
#     productions={
#         'E': [
#             ('LIST_WORDS', 'NUMBER'),
#         ],
#         'LIST_WORDS': ListProds('[', 'WORD', None, ']', optional=True),
#     },
# )
#
# x = parser.parse("[a b c] 10")  # TElement
# print(str(x))
#  > E:
#  >   LIST_WORDS: [
#  >     a
#  >     b
#  >     c
#  >   ]
#  >   NUMBER: 10
#
# assert x.value[0].name == 'LIST_WORDS'
# assert x.value[0].value == ['a', 'b', 'c']


import re
from collections import defaultdict
import collections.abc
from dataclasses import dataclass
import itertools
from typing import Tuple, Self
import logging


logger = logging.getLogger(__name__)


class Error(Exception):
    """Common parsing error"""
    pass


class SrcPos:
    """Human-readable description of a position in source text."""
    __slots__ = 'src_name', 'coords'

    def __init__(self, src_name, line, col):
        self.src_name = src_name
        self.coords = (line, col)

    @property
    def line(self):
        """Return line number of the position (first line has number 1)"""
        return self.coords[0]

    @property
    def col(self):
        """Return column number of the position (first column has number 1)"""
        return self.coords[1]


class LexicalError(Error):
    """Error happened during lexical parsing"""

    def __init__(self, src_pos, text, descr="unexpected symbol at"):
        self.src_pos = src_pos
        line, col = src_pos.coords
        self.text = text
        super().__init__(
            f"{descr} {src_pos.src_name}({line}, {col}):\n{text}\n" +
            " "*col + "^"*(len(text)-col))


class GrammarError(Error):
    """Incorrect grammar structure."""
    def __init__(self, parser_summary, msg):
        self.parser_summary = parser_summary
        if self.parser_summary is not None:
            msg = "\n".join(self.parser_summary.gen_detailed_descr()) + f"\n{msg}"
        super().__init__(msg)


class GrammarIsRecursive(GrammarError):
    """Grammar is recursive.

    Means that when we expand some symbol X we can come to situation when no
    tokens consumed, but the next symbol to expand is the same symbol X.
    """
    def __init__(self, parser_summary, cycle_data, nullables):
        msg = f"grammar is recursive:\n{nullables=}\n" + "\n".join(
            self._mk_prod_descr(cycle_element)
            for cycle_element in cycle_data
        )
        super().__init__(parser_summary, msg)

    @classmethod
    def _mk_prod_descr(cls, cycle_element):
        # make description of a production, highlight specified symbol
        symbol, prod, prod_symbol_id = cycle_element
        return f"'{symbol}' -> [" + ", ".join(
            f"<'{s}'>" if i == prod_symbol_id else f"'{s}'"
            for i, s in enumerate(prod.production)) + "]"


class ParsingError(Error):
    """Unexpected token kind of errors."""
    def __init__(self, symbol, next_tokens, attempted_prod_rules):
        self.src_pos = next_tokens[0].src_pos
        attempted_productions = [pr.production for pr in attempted_prod_rules]
        msg = (
            f"fail at {next_tokens}.\n"
            f"tried productions '{symbol}' -> {attempted_productions}")
        super().__init__(msg)


class _Token:
    # information about a single token
    # (first phase of parsing is to split text into tokens)
    __slots__ = 'name', 'src_pos', 'value'

    def __init__(self, name, src_pos, value):
        self.name = name
        self.src_pos = src_pos
        self.value = value

    def __str__(self):
        if self.src_pos is not None:
            s = f"{self.name}({self.src_pos.line},{self.src_pos.col}){{{self.value}}}"
        else:
            s = f"{self.name}(-,-){{{self.value}}}"
        return s

    def __repr__(self):
        return str(self)


class _Tokenizer:
    # split line of text into tokens
    class _Chunk:
        # line of text to tokenize
        __slots__ = "line_id", "start_pos", "text", "orig_text"
        def __init__(self, line_id, start_pos, text, orig_text):
            self.line_id = line_id
            self.start_pos = start_pos
            self.text = text
            self.orig_text = text if orig_text is None else orig_text

    def __init__(
            self,
            tokenizer_str,
            *,
            span_matchers=None,
            synonyms=None, keywords=None,
            end_token_name="$END$",
        ):
        """_Tokenizer constructor.

        Arguments:
        - end_token_name: name of special token which corresponds to no text
            and indicates end of the text.
        - Check LLParser class for description of other arguments.
        """
        self.matcher = re.compile(tokenizer_str, re.VERBOSE)
        self.span_matchers = self._prepare_span_matchers(span_matchers, self.matcher)
        self.synonyms = synonyms or {}
        self.keywords = keywords or {}
        self.end_token_name = end_token_name

    def get_all_token_names(self):
        """Get names of all tokens this tokenizer knows about."""
        tokens = set(self.matcher.groupindex.keys())
        tokens -= self.synonyms.keys()
        tokens.update(self.synonyms.values())
        tokens.update(self.keywords.values())
        return tokens

    def tokenize(self, text, src_name):
        """text -> _Token objects

        Arguments:
        - text: text to split into tokens. It may be:
          - string. In this case it is split into lines first
          - Iterable[str]

        Parsing is performed in two phases: first all comments are removed,
        then remaining text is split into tokens.
        Comments and 'space' tokens are not yielded.
        """
        if isinstance(text, str):
            enumereted_lines = enumerate(
                (t.rstrip() for t in text.split('\n')),
                start=1)
        elif isinstance(text, collections.abc.Iterable):
            enumereted_lines = enumerate(text, start=1)
        else:
            assert False, (
                f"unexpected type of the object to parse: {str(type(text))}")

        cur_span_symbol = None
        cur_span_start_text = None
        cur_span_start_pos = None
        cur_span_lines = None
        span_body_matcher = None

        for line_id, text_line in enumereted_lines:
            col = 0
            while col < len(text_line):
                if cur_span_symbol is not None:
                    # we are inside 'span' token (for example inside
                    # multi-line comment)
                    match = span_body_matcher.match(text_line, col)
                    if match is None:
                        # end of the span is not found on this line of text
                        cur_span_lines.append(text_line[col:])
                        col = len(text_line)
                    else:
                        # end of span found!
                        last_line = match.group(match.lastgroup)
                        cur_span_lines.append(last_line)
                        value = "\n".join(cur_span_lines)
                        token_name = self.synonyms.get(
                            cur_span_symbol, cur_span_symbol)
                        yield _Token(
                            token_name,
                            SrcPos(src_name, line_id, col + 1),
                            value)
                        cur_span_symbol = None
                        cur_span_start_text = None
                        cur_span_start_pos = None
                        cur_span_lines = None
                        span_body_matcher = None
                        col = match.end()
                else:
                    # we are not inside 'span', so usual token is expected
                    match = self.matcher.match(text_line, col)
                    if match is None:
                        raise LexicalError(SrcPos(src_name, line_id, col), text_line)
                    token_name = match.lastgroup
                    value = match.group(token_name)

                    span_body_matcher = self.span_matchers.get(token_name)
                    if span_body_matcher is not None:
                        # we found start of the 'span' token. Something
                        # like opening of a comment '/*'.
                        cur_span_symbol = token_name
                        cur_span_start_text = text_line
                        cur_span_start_pos = (line_id, col)
                        cur_span_lines = []
                    else:
                        token_name = self.synonyms.get(token_name, token_name)
                        keyword_token = self.keywords.get((token_name, value))
                        if keyword_token is not None:
                            # this token is not a word, but keyword
                            token_name = keyword_token
                        yield _Token(
                            token_name,
                            SrcPos(src_name, line_id, col + 1),
                            value)
                    col = match.end()

        if cur_span_symbol is not None:
            raise LexicalError(
                SrcPos(src_name, cur_span_start_pos[0], cur_span_start_pos[1]),
                cur_span_start_text,
                "span is never closed")

        yield _Token(
            self.end_token_name, None, None)

    @classmethod
    def _prepare_span_matchers(cls, span_matchers, matcher):
        # process 'span_matchers' argument of constructor: prepare
        # regex expressions for multiline tokens.
        result = {}
        if span_matchers is None:
            return result
        norm_re_group_names = set(matcher.groupindex.keys())
        for open_token_name, re_str in span_matchers.items():
            if open_token_name not in norm_re_group_names:
                raise GrammarError(
                    None,
                    f"unknows opening symbol '{open_token_name}' specified "
                    f"in 'span_matchers'. Each key of this dict must be a "
                    f"name of the re group specified in tokenizer string"
                )
            result[open_token_name] = re.compile(re_str, re.VERBOSE)
        return result


@dataclass(frozen=True)
class TElemSignature:
    """Info about TElement name and names of it's children."""
    name: str
    child_names: Tuple[str, ...]

    def __str__(self):
        prod = ", ".join(f"'{s}'" for s in self.child_names)
        return f"'{self.name}'[{prod}]"

    def __repr__(self):
        return str(self)

    def __eq__(self, other) -> bool:
        if isinstance(other, TElemSignature):
            return self.name == other.name and self.child_names == other.child_names
        if isinstance(other, (tuple, list)):
            if len(other) != len(self.child_names) + 1:
                return False
            if self.name != other[0]:
                return False
            return all(a == b for a, b in zip(self.child_names, other[1:]))
        return False


class TElement:
    """Element of tree, which represents parsing results.

    The value can be:
        - string - for terminal symbols
        - None - no values corresponding to the symbol (it must be nullable)
        - [TElement, ] - for non-terminal symbols
        Following cases are possible after cleanup process:
        - [misc_value, ] - for nodes, corresponding to list productions
        - {key: TElement} - for maps
    """
    __slots__ = 'name', 'value', '_is_leaf', 'src_pos'

    def __init__(self, name, value, *, src_pos=None, is_leaf=None):
        self.name = name
        self.value = value
        is_valid_inner_node = (
            isinstance(self.value, list)
            and all(isinstance(x, TElement) for x in self.value)
        )

        if is_leaf is None:
            self._is_leaf = not is_valid_inner_node
        else:
            self._is_leaf = is_leaf
            if not self._is_leaf:
                assert is_valid_inner_node, (
                    "for not-leaf elements the value must be a "
                    "list of TElement objects")

        if self._is_leaf:
            if self.value is not None:
                assert src_pos is not None, (
                    "src position must be explicitely specified for "
                    "not-null leaf elements")
            self.src_pos = src_pos
        else:
            if src_pos is not None:
                self.src_pos = src_pos
            else:
                assert is_valid_inner_node
                for t_elem in self.value:
                    if t_elem.src_pos is not None:
                        self.src_pos = t_elem.src_pos
                        break
                else:
                    # all the child elements of this TElement are nulls - there
                    # is no source text corresponding to this TElement
                    self.src_pos = None

    def __str__(self):
        return "\n".join(self.gen_descr())

    def __repr__(self):
        if self.is_leaf():
            return f"TE<{self.name}>/{self.value}/"
        else:
            return f"TE<{self.name}>[" + ",".join(
                repr(x) for x in self.value) + "]"

    def is_leaf(self) -> bool:
        """Check if self is a tree leaf."""
        return self._is_leaf

    def signature(self) -> TElemSignature:
        """Return tuple of symbols names.

        First element is self.name, names of child elements follow.
        """
        prod_tuple = () if self.is_leaf() else tuple(x.name for x in self.value)
        return TElemSignature(self.name, prod_tuple)

    def clone(self):
        """Create a copy of self."""
        return TElement(
            self.name, self._clone_value(self.value),
            src_pos=self.src_pos, is_leaf=self._is_leaf)

    @classmethod
    def _clone_value(cls, value):
        # helper method for 'clone'
        _clone = lambda x: x.clone() if isinstance(x, TElement) else x
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list):
            return [_clone(x) for x in value]
        if isinstance(value, dict):
            return {
                _clone(k): _clone(v)
                for k, v in value.items()
            }
        assert False, f"unexpected value: {value=} of type {str(type(value))}"

    def gen_descr(self, offset=0, out_name=None):
        """Generate lines of self description.

        Arguments:
        - out_name: 'outer' name of the self. For example, if
            TElement is a value of dictionary, we may want to generate the
            description including corresponding key. Disctionary key
            in this case is 'outer' name.
        """
        obj_descr = f"{self.name}" if out_name is None else f"{out_name}: {self.name}"
        if not self.is_leaf():
            yield "  " * offset + f"{obj_descr}:"
            for child in self.value:
                if child is None:
                    # this should be possible only in case self is a list,
                    # parsing results are cleaned-up, and the list contains
                    # None values.
                    yield "  " * (offset+1) + "None"
                else:
                    assert isinstance(child, TElement), f"{child=}"
                    yield from child.gen_descr(offset+1)
        else:
            yield from self._gen_obj_descr(self.value, offset, obj_descr)

    @classmethod
    def _gen_obj_descr(cls, obj, offset, out_name):
        # helper method for 'gen_descr'. Generates description of
        # objects which may be not TElement.
        prefix = f"{out_name}: " if out_name is not None else ""
        if isinstance(obj, dict):
            if len(obj) == 0:
                yield "  " * offset + f"{prefix}{{}}"
            else:
                yield "  " * offset + f"{prefix}{{"
                for map_key, map_value in obj.items():
                    yield from cls._gen_obj_descr(map_value, offset+1, map_key)
                yield "  " * offset + "}"
        elif isinstance(obj, list):
            if len(obj) == 0:
                yield "  " * offset + f"{prefix}[]"
            else:
                yield "  " * offset + f"{prefix}["
                for list_value in obj:
                    yield from cls._gen_obj_descr(list_value, offset+1, None)
                yield "  " * offset + "]"
        elif isinstance(obj, TElement):
            yield from obj.gen_descr(offset, out_name)
        else:
            yield "  " * offset + f"{prefix}{obj}"

    def printme(self):
        """Pretty-print the tree with root in self"""
        for x in self.gen_descr():
            print(x)

    def get(self, name, default=None):
        """Get child TElement by name.

        Exception is raised if more than one element with the same name exists.
        """
        if isinstance(self.value, dict):
            return self.value.get(name, default)
        if self.value is None:
            return default
        matches = [
            e
            for e in self.value
            if isinstance(e, TElement) and e.name == name
        ]
        if len(matches) == 0:
            return default
        elif len(matches) == 1:
            return matches[0]
        raise ValueError(
            f"{self} has {len(matches)} child elements with name '{name}'")

    def get_path_elem(self, path, default=None):
        """Get descendant by path.

        Exception is raised if on some step more than one element with the expected
        name exists.
        """
        if isinstance(path, str):
            path = path.split('.')

        cur_elem = self
        for p in path:
            if not isinstance(cur_elem, TElement):
                return default
            cur_elem = cur_elem.get(p)
        return cur_elem

    def get_path_val(self, path, default=None):
        """Get value of descendant by path.

        Exception is raised if on some step more than one element with the expected
        name exists.
        """
        t_elem = self.get_path_elem(path)
        if t_elem is None or t_elem.value is None:
            return default
        return t_elem.value


class ProdRule:
    """Info about production rule 'A' -> ('B', 'C', 'D').

    Name 'production' is used for the result symbols, ('B', 'C', 'D') in this case.
    """
    __slots__ = 'symbol', 'production', 'sort_n'

    def __init__(self, symbol, production, sort_n):
        self.symbol = symbol
        self.production = production
        self.sort_n = sort_n

    def __str__(self):
        return f"'{self.symbol}' -> {self.production} #{self.sort_n}"


#########################
# Production Templates

class ProdsTemplate:
    """Base class for Production Templates.

    Production Template is an object, which can generate multiple productions
    for LLParser grammar. Optionally it can post-process corresponding sub-tree
    of the parsing results.
    """
    CAN_POST_PROCESS_TELEM = True

    def __init__(self):
        self.result_symbol = None

    def _ensure_initialized(self):
        assert self.result_symbol is not None, (
            f"{self} is not initialized. Call 'complete_init' "
            f"method to complete initialzation")

    def complete_init(self, result_symbol: str, terminals, parser_summary) -> None:
        """Complete initialization.

        Method is called during construction of LLParser to let the ProdsTemplate
        the context where it was created.
        """
        _ = terminals
        _ = parser_summary
        assert self.result_symbol is None, (
            f"{self} is already initialized (with result symbol "
            f"'{self.result_symbol}')")
        self.result_symbol = result_symbol

    def verify_grammar(self, llparser, nullables, parser_summary):
        pass

    def gen_productions(self):
        assert False, f"not implemented in {str(type(self))}"
        yield from []

    @staticmethod
    def _find_index(symbols_list, symbol):
        # mini helper: list.index but returns None if item not found
        try:
            i = symbols_list.index(symbol)
        except ValueError:
            i = None
        return i


class ProdSequence(ProdsTemplate):
    """Productions which match a sequence of elements.

    Creates productions which match "any of given symbols in any order".
    Resulting TElement is a leaf, it's value is a list of matched TElement objects.
    """
    CAN_POST_PROCESS_TELEM = False

    def __init__(self, *symbols):
        super().__init__()
        self.symbols = list(symbols)
        self.element_symbol_name = None

    def complete_init(self, result_symbol, terminals, parser_summary) -> None:
        """Complete initialization."""
        assert result_symbol is not None
        super().complete_init(result_symbol, terminals, parser_summary)
        assert self.result_symbol is not None

        self.element_symbol_name = f"{self.result_symbol}__ELEMENT"

        # as of now self.symbols may contain special 'AnyTokenExcept' item.
        # It's time to replace it with actual tokens
        num_special_items = sum(
            1 if isinstance(s, AnyTokenExcept) else 0
            for s in self.symbols)
        if num_special_items > 1:
            raise GrammarError(
                parser_summary,
                f"production for symbol '{self.result_symbol}' contains "
                f"{num_special_items} 'AnyTokenExcept' elements. "
                f"Max allowed number is 1.")
        elif num_special_items == 1:
            new_ss = []
            for s in self.symbols:
                if isinstance(s, AnyTokenExcept):
                    new_ss.extend(
                        s.get_tokens(terminals, self.result_symbol, parser_summary))
                else:
                    new_ss.append(s)
            self.symbols = new_ss

    def gen_productions(self):
        """Generate the productions to match the sequence of elements."""
        self._ensure_initialized()
        # Corresponding productions are similar to productions of a list
        # 'THE_SEQUENCE': [
        #    ('SEQUENCE__ELEMENT', 'THE_SEQUENCE'),
        #    None,
        #  ]
        yield self.result_symbol, [
            (self.element_symbol_name, self.result_symbol),
            (),
        ]
        # 'SEQUENCE__ELEMENT': [
        #    (symbol, ),
        #    ...
        #  ]
        yield self.element_symbol_name, [
            (s, ) for s in self.symbols
        ]


class ListProds(ProdsTemplate):
    """Production Template for matching list structures.

    Instead of specifying all the productions required to parse a list of some
    items in LLParser constructor, it is possible to specify a single template:

    'LIST_PROD': ListProds(
        '[', 'LIST_ITEM', ',', ']',
        allow_final_delimiter=True, optional=False)

    It is necessary to specify name of the symbol corresponding to the list item,
    but None can be specified in place of '[', ',', ']',
    """
    def __init__(
        self,
        open_br: str, item_symbol: str, delimiter: str, close_br: str, *,
        allow_final_delimiter=None,
        optional=None,
    ):
        """ListProds constructor.

        Arguments:
        - open_br: optional name of "open bracket" symbol
        - item_symbol: name of the symbol of list item
        - delimiter: name of list delimiter symbol
        - close_br: optional name of "close bracket" symbol
        - allow_final_delimiter: allow lists like [1, 2, 3, ]
        - optional: indicates that the whole list is optional

        Example:
        'LIST_PROD': ListProds('[', 'LIST_ITEM', ',', ']')

        """
        assert (open_br is None) == (close_br is None), (
            f"'open_br' and 'close_br' can be None only simultaneously: "
            f"{open_br=}; {close_br=}")

        if allow_final_delimiter is None:
            allow_final_delimiter = delimiter is not None and open_br is not None

        if allow_final_delimiter:
            assert delimiter is not None and open_br is not None, (
                f"In ListProd for '{item_symbol}': allow_final_delimiter can "
                f"be True only if open_br, close_br and delimiter are not None")

        if optional is not None:
            assert open_br is not None, (
                f"'optional' argument is implemented only for lists with brackets")
        else:
            optional = False

        super().__init__()

        self.open_br = open_br
        self.item_symbol = item_symbol
        self.delimiter = delimiter
        self.close_br = close_br
        self.allow_final_delimiter = allow_final_delimiter
        self.optional = optional

        self.list_tail_symbol = None
        self.list_prods_signatures = None
        self.tail_prods_signatures = None

    def complete_init(self, result_symbol, terminals, parser_summary) -> None:
        """Complete initialization."""
        assert result_symbol is not None
        super().complete_init(result_symbol, terminals, parser_summary)
        assert self.result_symbol is not None

        has_brackets = self.open_br is not None
        has_separator = self.delimiter is not None

        if has_brackets or has_separator:
            self.list_tail_symbol = f"{self.result_symbol}__TAIL"
        else:
            self.list_tail_symbol = self.result_symbol

        # list_prods
        # 'THE_LIST': [
        #     ('[', ']'),
        #     ('[', 'ITEM', 'THE_LIST__TAIL', ']'),
        #     None,   <- only if self.optional
        # ],
        list_prods = [
            [self.open_br, self.close_br],
            [self.open_br, self.item_symbol, self.list_tail_symbol, self.close_br],
        ]
        if not has_brackets:
            # for lists with brackets it is important that ('[', ']') production
            # goes first. So that "[ ]" be interpreted as empty list, not a list
            # with None element inside (in case 'ITEM' is nullable).
            #
            # But in case there are no brackets it is necessary to try "empty list"
            # option only if the list in empty indeed
            list_prods.reverse()

        if self.optional:
            list_prods.append([])

        if self.list_tail_symbol == self.result_symbol:
            # it happens iff there are no brakets and no separator
            # in this case there is no need to use separate symbol for tail
            list_tail_prods = list_prods
        else:
            # list_tail_prods
            #
            # 'THE_LIST__TAIL': [
            #     (',', 'ITEM', 'THE_LIST__TAIL'),
            #     (',', ),     <- if last delimiter allowed
            #     None,
            # ],
            list_tail_prods = [
                [self.delimiter, self.item_symbol, self.list_tail_symbol],
                [self.delimiter, ],
                [],
            ]
            if not self.allow_final_delimiter:
                list_tail_prods.pop(1)

        # now list_prods and list_tail_prods contain names of symbols
        # for LIST and LIST__TAIL productions. But these lists
        # may contain None values in place of delimiter.
        # Following methods will purge these extra items.

        self.list_prods_signatures = dict(
            self._make_expected_signature(self.result_symbol, prod)
            for prod in list_prods
        )
        self.tail_prods_signatures = dict(
            self._make_expected_signature(self.list_tail_symbol, prod)
            for prod in list_tail_prods
        )

    def verify_grammar(self, llparser, nullables, parser_summary):
        """Verify that ListProds is compatible with the LLParser."""
        if self.delimiter is None and self.item_symbol in nullables:
            raise GrammarError(
                parser_summary,
                f"List item symbol '{self.item_symbol}' is nullable. "
                f"It is prohibited for lists without separator symbol.")

    def _make_expected_signature(self, symbol, prod_symbols):
        # constructor helper, prepares signatures of expected TElement objects
        # and positions of 'item' and 'tail' child elements
        prod_symbols = tuple(s for s in prod_symbols if s is not None)

        signature = TElemSignature(symbol, prod_symbols)
        positions = (
            self._find_index(prod_symbols, self.item_symbol),
            self._find_index(prod_symbols, self.list_tail_symbol),
        )
        return signature, positions

    def __str__(self):
        result = self.result_symbol or "??"
        op = "" if self.open_br is None else self.open_br
        cl = "" if self.close_br is None else self.close_br
        sep = "" if self.delimiter is None else f"{self.delimiter} "
        return (
            f"{type(self).__name__}<{result} -> "
            f"{op}{self.item_symbol}{sep}...{cl}>")

    def gen_productions(self):
        """Generate grammar productions."""
        self._ensure_initialized()

        yield self.result_symbol, [
            signature.child_names
            for signature in self.list_prods_signatures.keys()
        ]

        if self.list_tail_symbol != self.result_symbol:
            # these symbols are equal iff no brackets are used.
            # in this case self.tail_prods_signatures contains same
            # signatures as self.list_prods_signatures, so no need
            # to generate additional productions
            yield self.list_tail_symbol, [
                signature.child_names
                for signature in self.tail_prods_signatures.keys()
            ]

    def transform_t_elem(self, t_elem: TElement, cleanuper) -> None:
        """Transform subtree corresponding to the list into a single TElement.

        Result TElement is a leaf, it's value is a list of parsed values.
        """
        signature = t_elem.signature()
        assert signature in self.list_prods_signatures, (
            f"Can't make a list from TElement {t_elem} with signature "
            f"{signature}. Expected TElement with one of following signatures: \n"
            f"{', '.join(s for s in sorted(self.list_prods_signatures))}")
        item_elem_pos, tail_elem_pos = self.list_prods_signatures[signature]

        if self.optional and t_elem.value is None:
            return

        values_list = []
        if item_elem_pos is not None:
            item_t_elem = t_elem.value[item_elem_pos]
            cleanuper._cleanup(item_t_elem, for_container=True)
            values_list.append(item_t_elem)

        if tail_elem_pos is not None:
            tail_t_elem = t_elem.value[tail_elem_pos]
            self._parse_tail_t_elem(tail_t_elem, cleanuper, values_list)

        # new_values now contains TElement objects.
        # If some TElement is a leaf - replace it with it's value
        values_list = [
            x.value if x.is_leaf() else x
            for x in values_list
        ]

        if (
            len(values_list) > 0
            and values_list[-1] is None
            and self.allow_final_delimiter
        ):
            # "[1, 2, 3, ]" may be interpreted as ["1", "2", "3", None].
            # Do not do it if final delimiter is allowed.
            values_list.pop()
        elif (
            self.open_br is None
            and len(values_list) == 1
            and values_list[0] is None
        ):
            # missing list without brackets may be interpreted as containing a single
            # None value. But empty list is a more apropriate interpretation.
            values_list = []

        t_elem._is_leaf = True
        t_elem.value = values_list

    def _parse_tail_t_elem(self, t_elem: TElement, cleanuper, values_list) -> None:
        # helper for self.transform_t_elem.
        # process subtree corresponding to 'THE_LIST__TAIL' symbol.
        signature = t_elem.signature()
        assert signature in self.tail_prods_signatures, (
            f"Unexpected TElement {t_elem} with signature {signature} encountered "
            f"while processing list tail. Expected TElement with one of following "
            f"signatures: \n"
            f"{', '.join(s for s in sorted(self.tail_prods_signatures))}")
        item_elem_pos, tail_elem_pos = self.tail_prods_signatures[signature]

        if item_elem_pos is not None:
            item_t_elem = t_elem.value[item_elem_pos]
            cleanuper._cleanup(item_t_elem, for_container=True)
            values_list.append(item_t_elem)

        if tail_elem_pos is not None:
            tail_t_elem = t_elem.value[tail_elem_pos]
            self._parse_tail_t_elem(tail_t_elem, cleanuper, values_list)


class MapProds(ProdsTemplate):
    """Production Template for matching map-like structures.

    Instead of specifying all the productions required to parse a map of some
    items in LLParser constructor, it is possible to specify a single template:

    'MAP_PROD': llparser.MapProds('{', 'WORD', ':', 'VALUE', ',', '}'),
    """

    def __init__(
        self, open_br: str,
        key_symbol: str, assign_symbol: str, val_symbol: str,
        delimiter: str, close_br: str, *,
        optional=None,
        allow_final_delimiter=True,
    ):
        """MapProds constructor.

        Arguments:
        - open_br: name of "open bracket" symbol
        - key_symbol: name of the symbol of map key item
        - assign_symbol: name of the 'assignment' symbol
        - val_symbol: name of the symbol of map key item
        - delimiter: name of list delimiter symbol
        - close_br: name of "close bracket" symbol
        - allow_final_delimiter: allow maps like "{a=1, b=2, }"
        - optional: indicates that the whole list is optional

        Example:
        'MAP_PROD': llparser.MapProds('{', 'WORD', ':', 'VALUE', ',', '}'),
        """

        assert (open_br is None) == (close_br is None), (
            f"'open_br' and 'close_br' can be None only simultaneously: "
            f"{open_br=}; {close_br=}")

        assert assign_symbol is not None
        assert delimiter is not None

        if optional is not None:
            assert open_br is not None, (
                f"'optional' argument is implemented only for lists with brackets")
        else:
            optional = False

        super().__init__()

        self.open_br = open_br
        self.key_symbol = key_symbol
        self.assign_symbol = assign_symbol
        self.val_symbol = val_symbol
        self.delimiter = delimiter
        self.close_br = close_br
        self.optional = optional
        self.allow_final_delimiter = allow_final_delimiter

        self.kv_pair_symbol = None
        self.kv_tail_symbol = None

        self.map_prods_signatures = None
        self.kv_tail_prods_signatures = None
        self.kv_prod_signature = None

    def complete_init(self, result_symbol, terminals, parser_summary) -> None:
        """Complete initialization."""
        assert result_symbol is not None
        super().complete_init(result_symbol, terminals, parser_summary)
        assert self.result_symbol is not None

        self.kv_pair_symbol = f"{self.result_symbol}__KV_PAIR"
        self.kv_tail_symbol = f"{self.result_symbol}__ELEMENTS"

        # map_prods
        # 'THE_MAP': [
        #     ('{', '}'),
        #     ('{', 'THE_MAP__KV_PAIR', 'THE_MAP__KV_TAIL', '}'),
        #     None,    <- only if self.optional
        # ],
        map_prods = [
            [self.open_br, self.close_br],
            [self.open_br, self.kv_pair_symbol, self.kv_tail_symbol, self.close_br],
        ]
        if self.optional:
            map_prods.append([])

        # map_kv_tail
        # 'THE_MAP__KV_TAIL': [
        #     (',', 'THE_MAP__KV_PAIR', 'THE_MAP__KV_TAIL'),
        #     (',', ),  <- if last delimiter allowed
        #     None,
        # ],
        map_kv_tail_prods = [
            [self.delimiter, self.kv_pair_symbol, self.kv_tail_symbol],
            [self.delimiter, ],
            [],
        ]
        if not self.allow_final_delimiter:
            map_kv_tail_prods.pop(1)

        # kv_prod
        # 'THE_MAP__KV_PAIR': [
        #     ('KEY', ':', 'VALUE'),
        # ]
        kv_prod = [self.key_symbol, self.assign_symbol, self.val_symbol]

        self.map_prods_signatures = dict(
            self._make_expected_signature(self.result_symbol, prod)
            for prod in map_prods
        )
        self.kv_tail_prods_signatures = dict(
            self._make_expected_signature(self.kv_tail_symbol, prod)
            for prod in map_kv_tail_prods
        )
        self.kv_prod_signature = TElemSignature(self.kv_pair_symbol, tuple(kv_prod))

    def _make_expected_signature(self, symbol, prod_symbols):
        # constructor helper, prepares signatures of expected TElement objects
        # and positions of 'kv_pair' and 'kv_tail' child elements
        prod_symbols = tuple(s for s in prod_symbols if s is not None)

        signature = TElemSignature(symbol, prod_symbols)
        positions = (
            self._find_index(prod_symbols, self.kv_pair_symbol),
            self._find_index(prod_symbols, self.kv_tail_symbol),
        )
        return signature, positions

    def __str__(self):
        result = self.result_symbol or "??"
        sep = "" if self.delimiter is None else f"{self.delimiter} "

        return (
            f"{type(self).__name__}<{result} -> "
            f"{self.open_br}{self.key_symbol}{self.assign_symbol}"
            f"{self.val_symbol}{sep}...{self.close_br}>")

    def gen_productions(self):
        """Generate grammar productions."""
        self._ensure_initialized()

        yield self.result_symbol, [
            signature.child_names
            for signature in self.map_prods_signatures.keys()
        ]

        yield self.kv_tail_symbol, [
            signature.child_names
            for signature in self.kv_tail_prods_signatures.keys()
        ]

        yield self.kv_pair_symbol, [
            self.kv_prod_signature.child_names
        ]

    def transform_t_elem(self, t_elem: TElement, cleanuper) -> None:
        """Transform subtree corresponding to the map into a single TElement.

        Result TElement is a leaf, it's value is the map of parsed keys/values.
        """
        signature = t_elem.signature()
        assert signature in self.map_prods_signatures, (
            f"Can't make a map from TElement {t_elem} with signature "
            f"{signature}. Expected TElement with one of following signatures: \n"
            f"{', '.join(s for s in sorted(self.map_prods_signatures))}")
        kv_pair_pos, kv_tail_pos = self.map_prods_signatures[signature]

        if self.optional and t_elem.value is None:
            return

        kv_pairs = []
        if kv_pair_pos is not None:
            kv_pair = self._parse_kv_pair(t_elem.value[kv_pair_pos], cleanuper)
            kv_pairs.append(kv_pair)

        if kv_tail_pos is not None:
            self._parse_kv_tail(t_elem.value[kv_tail_pos], cleanuper, kv_pairs)

        t_elem._is_leaf = True
        t_elem.value = dict(kv_pairs)

    def _parse_kv_tail(self, t_elem: TElement, cleanuper, kv_pairs):
        # helper for self.transform_t_elem.
        # process subtree corresponding to 'THE_MAP__KV_TAIL' symbol.
        signature = t_elem.signature()
        assert signature in self.kv_tail_prods_signatures, (
            f"Unexpected TElement {t_elem} with signature {signature} encountered "
            f"while processing map contents. Expected TElement with one of following "
            f"signatures: \n"
            f"{', '.join(s for s in sorted(self.kv_tail_prods_signatures))}")
        kv_pair_pos, kv_tail_pos = self.kv_tail_prods_signatures[signature]

        if kv_pair_pos is not None:
            kv_pair = self._parse_kv_pair(t_elem.value[kv_pair_pos], cleanuper)
            kv_pairs.append(kv_pair)

        if kv_tail_pos is not None:
            self._parse_kv_tail(t_elem.value[kv_tail_pos], cleanuper, kv_pairs)

    def _parse_kv_pair(self, t_elem: TElement, cleanuper):
        # helper for self.transform_t_elem.
        # process subtree corresponding to 'THE_MAP__KV_PAIR' symbol.
        signature = t_elem.signature()

        assert signature == self.kv_prod_signature, (
            f"Unexpected TElement {t_elem} with signature {signature} encountered "
            f"while processing map's key-value pair. Expected TElement with "
            f"signature: {self.kv_prod_signature}")

        key_elem = t_elem.value[0]
        val_elem = t_elem.value[2]

        cleanuper._cleanup(key_elem, for_container=True)
        cleanuper._cleanup(val_elem, for_container=True)

        key = key_elem.value if key_elem.is_leaf() else key_elem
        val = val_elem.value if val_elem.is_leaf() else val_elem

        return (key, val)


class AnyTokenExcept:
    """Argument of LLParser constructor.

    Indicates that a number of one-token Production Rules should be created:
    "(token, )" for each token except of specified ones.
    """
    def __init__(self, *tokens):
        self.tokens = tokens

    def get_tokens(self, terminals, for_symbol, parser_summary):
        """Get list of all terminals except those specified for constructor.

        Arguments:
        - terminals: all the terminals
        - for_symbol: context (for reporting purposes only).
        """
        tokens_to_exclude = set(self.tokens)
        unexpected_tokens = tokens_to_exclude - terminals
        if unexpected_tokens:
            raise GrammarError(
                parser_summary,
                f"unknown terminal(s) specified in 'AnyTokenExcept' item: "
                f"of productions of symbol '{for_symbol}': {unexpected_tokens}")
        return [t for t in terminals if t not in tokens_to_exclude]


class _StackElement:
    # represents current position of parsing
    #
    # means: we try to match symbol starting from a token at given position
    # we have already matched first several symbols of current production
    # corresponding match results are stored in values
    def __init__(self, symbol, token_pos, prod_rs):
        self.symbol = symbol
        self.start_token_pos = token_pos
        self.cur_token_pos = token_pos
        self.prod_rs = prod_rs  # [ProdRule, ]
        self.cur_prod_id = 0
        self.values = []
        self.log_offset = 0

    def clone(self):
        """clone self"""
        clone = _StackElement(self.symbol, self.start_token_pos, self.prod_rs)
        clone.cur_token_pos = self.cur_token_pos
        clone.cur_prod_id = self.cur_prod_id
        clone.values = self.values[:]
        return clone

    def get_cur_prod(self) -> ProdRule:
        return self.prod_rs[self.cur_prod_id]

    def get_cur_symbol(self):
        """Gen next unmatched symbol in current production."""
        return self.prod_rs[self.cur_prod_id].production[len(self.values)]

    def next_matched(self, value, new_token_pos):
        """Register found matching value for current symbol in current production."""
        if value is None:
            # current symbol matches null production
            assert self.cur_token_pos == new_token_pos
            assert len(self.values) == 0
            self.values.append(TElement(None, None))
            return

        assert isinstance(value, TElement)
        self.values.append(value)
        self.cur_token_pos = new_token_pos

    def switch_to_next_prod(self):
        self.values = []
        self.cur_token_pos = self.start_token_pos
        self.cur_prod_id += 1


class ParserSummary:
    """Contains information about LLParser. Used for reporting only.

    This class keeps information about LLParser even if the LLParser's construction
    failed. To report such errors it's good to have all parser's properties
    accumulated in the single place.
    """

    def __init__(self):
        self.terminals = None
        self.orig_prods_map = None
        self.prods_map = None
        self.parse_table = None
        self.nullables = None
        self.first_sest = None
        self.follow_sets = None
        self.cleanuper = None

    def gen_detailed_descr(self):
        """Generate lines of human-readable description of the LLParser."""
        mk_descr_len = lambda x, size: f"'{x}'" + " "*(max(0, size - len(str(x))))

        yield "= Parser summary ="
        yield ""
        if self.terminals is None:
            yield "-- no parser data ready yet --"
            return
        yield f"Terminals: {self.terminals}"
        yield ""
        yield from self._descr_prods_map("Original Productions", self.orig_prods_map)
        yield ""
        yield from self._descr_prods_map("Factorized Productions", self.prods_map)
        yield ""

        if self.parse_table is None:
            yield "Parse Table: <n/a>"
        else:
            yield "Parse Table:"
            cur_symbol = None
            for (symbol, token), prod_rs in self.parse_table.items():
                if symbol != cur_symbol:
                    yield f"    '{symbol}':"
                    cur_symbol = symbol
                token_descr = mk_descr_len(token, 10)
                for prod in prod_rs:
                    yield f"        {token_descr}->{prod.production}"
        yield ""

        if self.nullables is None:
            yield "Nullables: <n/a>"
            yield "Not Nullables: <n/a>"
        else:
            yield f"Nullables: {self.nullables}"
            not_nullables = self.prods_map.keys() - self.nullables
            yield f"Not Nullables: {not_nullables}"
        yield ""

        if self.first_sest is None:
            yield "FirstSets: <n/a>"
        else:
            yield "FirstSets:"
            for symbol, firsts in sorted(self.first_sest.items()):
                yield f"    {mk_descr_len(symbol, 10)}: {sorted(firsts)}"
        yield ""

        if self.follow_sets is None:
            yield "FollowSets: <n/a>"
        else:
            yield "FollowSets:"
            for symbol, follows in sorted(self.follow_sets.items()):
                yield f"    {mk_descr_len(symbol, 10)}: {sorted(follows)}"
        yield ""

        if self.cleanuper is None:
            yield "Cleanup Rules: <n/a>"
        else:
            yield "Cleanup Rules:"
            yield from self.cleanuper.gen_detailed_descr()
        yield ""

    def _descr_prods_map(self, map_name, prods_map):
        # generates description of grammar's productions
        if prods_map is None:
            yield f"{map_name}: <n/a>"
            return
        yield f"{map_name}:"
        for prod_rs in prods_map.values():
            yield ""
            for rule in prod_rs:
                yield f"    {rule}"


class LLParser:
    """LLParser. Mostly LL1, but can deal with ambiguities in LL1 parsing table."""

    _END_TOKEN_NAME = '$END$'
    _INIT_PRODUCTION_NAME = '$START$'

    def __init__(
            self,
            tokenizer_str,
            *,
            productions,
            synonyms=None,
            span_matchers=None,
            keywords=None,
            skip_tokens=None,
            start_symbol_name='E',
            keep_symbols=None,
            smart_factorization=True,
        ):
        r"""Constructor of LLParser.

        Arguments:
        - tokenizer_str: re pattern for tokenizer. Example:
            r'''
            "(?P<DQ_STRING>[^"]*)"
            |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
            |(?P<MINUS>-)
            '''
        - productions: {symbol: [production, ]}
        - synonyms: {name_of_re_pattern: name_of_token}.
            Usually used to replace names like 'PLUS' -> '+', and in case when
            different patterns correspond to same token (doble-quote string and
            single-quote string correspond to the same token type 'STRING')
        - keywords: {(token_name, value): token_name}. Some token (name, value)
            combinations indicate are reported as token of other type. For
            example:
            {('WORD', 'class'): 'CLASS'}
        - skip_tokens: set of names of tokens which should be skipped - usually
            tokens corresponding to empty spaces and comments. By default
            'SPACE' and 'COMMENT' tokens are skipped.
        - start_symbol_name: name of the symbol
        - span_matchers: disctionary of regexps for processing 'span' tokens - tokens
            whose values may span between several lines. For example, to match
            c-style comments (/* ....... */) the tokenizer_str should contain
            group for 'opening' symbols ("|(?P<COMMENT_ML>/\*)") and the
            span_matchers dictionary should contain corresponding mask for "anything
            till '*/' symbols combination":
            {'COMMENT_ML': r"(?P<END_COMMENT>(\*[^/]|[^*])*)\*/"}
        - keep_symbols: names of symbols which should not be cleaned-up during
            optional cleanup procedure. Check doc of 'cleanup' method.
        """
        self.tokenizer = _Tokenizer(
            tokenizer_str,
            span_matchers=span_matchers,
            synonyms=synonyms, keywords=keywords)

        self.terminals = self.tokenizer.get_all_token_names()

        # used only for printing detailed description of the parser
        self._summary = ParserSummary()
        self._summary.terminals = self.terminals

        bad_terminals = [t for t in self.terminals if '__' in t]
        assert not bad_terminals, (
            f"Invalid terminals names detected: {bad_terminals}. "
            f"Names containing '__' are reserved")

        if skip_tokens is None:
            # by default we skip 'SPACE' and 'COMMENT' tokens
            self.skip_tokens = {
                t for t in ['SPACE', 'COMMENT'] if t in self.terminals}
        else:
            self.skip_tokens = set(skip_tokens)
            unexpected = self.skip_tokens - self.terminals
            if unexpected:
                raise GrammarError(
                    self._summary,
                    f"uknown token names specified in 'skip_tokens' "
                    f"arg: {unexpected}")

        self.start_symbol_name = start_symbol_name
        orig_prods_map, self._seq_symbols, self.prod_templates = (
            self._create_productions(productions, self.terminals, self._summary))
        self._summary.orig_prods_map = orig_prods_map

        self.prods_map, self._suffix_symbols = self._factorize_productions(
            orig_prods_map, self.terminals, smart_factorization)

        # TODO: order of these operations is strange and unexpected.
        # do something with it.
        self.terminals.add(self._END_TOKEN_NAME)

        self._summary.prods_map = self.prods_map

        self._verify_grammar_structure_part1(self._summary)

        self.prods_map[self._INIT_PRODUCTION_NAME] = [
            ProdRule(
                self._INIT_PRODUCTION_NAME,
                (self.start_symbol_name, self._END_TOKEN_NAME, ),
                -1,
            )
        ]

        nullables = self._get_nullables(self.prods_map)
        self._summary.nullables = nullables

        for prod_template in self.prod_templates.values():
            prod_template.verify_grammar(self, nullables, self._summary)

        self.cleanuper = StdCleanuper.make(self, keep_symbols)
        self._summary.cleanuper = self.cleanuper

        self.parse_table, first_sets, follow_sets = self._make_llone_table(
            self.prods_map, self.terminals, nullables,
            self.start_symbol_name,
        )
        self._summary.parse_table = self.parse_table
        self._summary.first_sest = first_sets
        self._summary.follow_sets = follow_sets

        self._verify_grammar_structure_part2(nullables, self._summary)

    def parse(self, text, *, src_name="input text", debug=False, do_cleanup=True):
        """Parse the text."""
        tokens = [
            t for t in self.tokenizer.tokenize(text, src_name)
            if t.name not in self.skip_tokens
        ]

        parse_stack = []  # [_StackElement, ]
        def _put_on_stack(stack_elem):
            parse_stack.append(stack_elem)
            if len(parse_stack) > 1:
                prev_top = parse_stack[-2]
                stack_elem.log_offset = prev_top.log_offset
                if (stack_elem.symbol != prev_top.symbol
                    or stack_elem.symbol not in self._seq_symbols
                ):
                    stack_elem.log_offset += 1

        # init parse stack
        _put_on_stack(_StackElement(
            self._INIT_PRODUCTION_NAME, 0,
            self.prods_map[self._INIT_PRODUCTION_NAME]))

        longest_stack = []
        if debug:
            self._log_cur_prod(parse_stack, tokens)

        while True:
            top = parse_stack[-1]
            cur_prod = top.get_cur_prod()
            if len(top.values) == len(cur_prod.production):
                # production matched
                if debug:
                    self._log_match_result(parse_stack, tokens)
                new_elem_value = top.values

                if len(new_elem_value) == 0:
                    # result of the production is empty.
                    # really not sure if to leave it [] or make it None.
                    new_elem_value = None

                t_elem = TElement(top.symbol, new_elem_value)
                if (len(cur_prod.production) > 0
                    and cur_prod.production[-1] in self._suffix_symbols
                ):
                    # this production corresponds to a factorized group
                    # X -> (..common prefix.., X_Sxx)
                    # It's time to merge suffix contents into self
                    suffix_elem = t_elem.value.pop()
                    if suffix_elem.value is not None:
                        t_elem.value.extend(suffix_elem.value)

                new_token_pos = top.cur_token_pos
                parse_stack.pop()

                if t_elem.name in self._seq_symbols:
                    self._process_seq_telement(t_elem)

                if not parse_stack:
                    # success!
                    # t_elem now is the TElement corresponding to technical
                    # initial production '$START$' -> ('E', '$END$').
                    assert len(t_elem.value) == 2
                    root = t_elem.value[0]
                    if debug:
                        print("RAW RESULT:")
                        root.printme()
                    if do_cleanup:
                        self.cleanuper.cleanup(root)
                        if debug:
                            print("FINAL RESULT:")
                            root.printme()
                    return root
                top = parse_stack[-1]
                top.next_matched(t_elem, new_token_pos)
                continue
            next_token = tokens[top.cur_token_pos]
            cur_symbol = top.get_cur_symbol()

            if cur_symbol in self.terminals:
                # try to match current token with next symbol
                if next_token.name == cur_symbol:
                    top.next_matched(
                        TElement(
                            cur_symbol, next_token.value,
                            src_pos=next_token.src_pos,
                        ),
                        top.cur_token_pos+1)
                    continue
            else:
                # next symbol is not terminal. Productions which potentially
                # can match this symbol:
                prods = self.parse_table.get((cur_symbol, next_token.name))
                if prods is not None:
                    _put_on_stack(_StackElement(cur_symbol, top.cur_token_pos, prods))
                    if debug:
                        self._log_cur_prod(parse_stack, tokens)
                    continue

            # current production does not match. Try to rollback
            # and attempt other options
            # Find rollback point
            if debug:
                self._log_match_result(parse_stack, tokens)
            if (
                not longest_stack
                or longest_stack[-1].cur_token_pos < parse_stack[-1].cur_token_pos
            ):
                longest_stack = [x.clone() for x in parse_stack]

            rollback_point = len(parse_stack) - 1
            while rollback_point >= 0:
                elem = parse_stack[rollback_point]
                if elem.cur_prod_id < len(elem.prod_rs) - 1:
                    # yes, we can try next production on this stack element
                    break
                rollback_point -= 1
            if rollback_point >= 0:
                parse_stack = parse_stack[:rollback_point+1]
                parse_stack[-1].switch_to_next_prod()
                if debug:
                    self._log_cur_prod(parse_stack, tokens)
                continue

            # report fail. Looks like it's good idea to describe the path
            # which reached fartherst when trying to parse the text
            top = longest_stack[-1] if longest_stack else parse_stack[-1]
            next_tokens = tokens[top.start_token_pos:top.start_token_pos+5]
            attempted_prods = top.prod_rs
            raise ParsingError(top.symbol, next_tokens, attempted_prods)

    def cleanup(self, t_elem: TElement) -> None:
        """Clean up the tree with root in TElement.

        Usually the cleanup is performed in parse method, in this case there is
        no need to repeat the cleanup. Use this method only if parse was called
        with do_cleanup=False.
        """
        if self.cleanuper is None:
            logger.warning(
                "LLParser %s was created without cleanuper, skip cleanup operation",
                self)
            return
        self.cleanuper.cleanup(t_elem)

    def is_ambiguous(self) -> bool:
        """Checks if grammar is LL1.
        That is there is no more than one production for (symbol, next_token) pair.
        """
        return any(len(prods) != 1 for prods in self.parse_table.values())

    def _verify_grammar_structure_part1(self, parser_summary):
        # initial verification of grammar structure
        # to be called before parse_table is prepared
        #
        # reports only very obvious problems. Less obvious problems
        # can be detected and/or properly reported only after parser is prepared
        if self.start_symbol_name not in self.prods_map:
            raise GrammarError(
                parser_summary,
                f"no productions for start symbol '{self.start_symbol_name}'")

        if self._END_TOKEN_NAME in self.prods_map:
            raise GrammarError(
                parser_summary,
                f"production specified for end symbol '{self._END_TOKEN_NAME}'")

        if self._INIT_PRODUCTION_NAME in self.prods_map:
            raise GrammarError(
                parser_summary,
                f"production specified explicitely for "
                f"special symbol '{self._INIT_PRODUCTION_NAME}'")

        non_terminals = set(self.prods_map.keys())
        bad_tokens = non_terminals.intersection(self.terminals)

        if bad_tokens:
            raise GrammarError(
                parser_summary,
                f"ProdRule(s) specified for terminal symbols {bad_tokens}")

        all_prod_symbols = {
            s
            for prod_rules in self.prods_map.values()
            for rule in prod_rules
            for s in rule.production}
        unknown_symbols = all_prod_symbols.difference(
            self.terminals | non_terminals)

        if unknown_symbols:
            raise GrammarError(
                parser_summary,
                f"unexpected symbols {unknown_symbols} used in productions")

        if self._END_TOKEN_NAME in all_prod_symbols:
            raise GrammarError(
                parser_summary,
                f"special end token '{self._END_TOKEN_NAME}' is explicitely "
                f"used in productions")

        if self._INIT_PRODUCTION_NAME in all_prod_symbols:
            raise GrammarError(
                parser_summary,
                f"special start symbol '{self._INIT_PRODUCTION_NAME}' is explicitely "
                f"used in productions")

    def _verify_grammar_structure_part2(self, nullables, parser_summary):
        # verification of grammar structure
        # to be called after parse_table is prepared

        # make sure grammar is not recursive - that is that it's not
        # possible that if we try to expand a symbol in several steps
        # we end up trying to exand same symbol but have not consumed
        # any tokens
        processed_symbols = set(self.terminals)
        for symbol, prod_rules in sorted(self.prods_map.items()):
            # depth-first-search of the same symbol
            if symbol in processed_symbols:
                continue
            # (symbol, prod_rules, cur_prod_id, cur_symbol_id)
            stack = [[symbol, prod_rules, 0, 0], ]
            def _next_prod(_stack):
                _stack[-1][2] += 1
                _stack[-1][3] = 0

            def _next_symbol(_stack):
                _stack[-1][3] += 1

            while stack:
                top = stack[-1]
                prod_symbol, prod_rules, cur_prod_id, cur_symbol_id = top
                if cur_prod_id >= len(prod_rules):
                    stack.pop()
                    processed_symbols.add(prod_symbol)
                    if stack:
                        top = stack[-1]
                        cur_prod = top[1][top[2]]
                        cur_prod_symbol = cur_prod.production[top[3]]
                        if cur_prod_symbol in nullables:
                            _next_symbol(stack)
                        else:
                            _next_prod(stack)
                    continue
                cur_prod = prod_rules[cur_prod_id]
                if cur_symbol_id >= len(cur_prod.production):
                    _next_prod(stack)
                    continue
                cur_symbol = cur_prod.production[cur_symbol_id]
                # check if this symbol is already present on stack
                for i, (stack_symbol, _, _, _) in enumerate(stack):
                    if stack_symbol == cur_symbol:
                        # found cycle
                        cycle_data = [
                            (s, prod_rules[prod_id], symbol_id)
                            for s, prod_rules, prod_id, symbol_id in stack[i:]
                        ]
                        raise GrammarIsRecursive(
                            parser_summary, cycle_data, nullables)

                if cur_symbol in processed_symbols:
                    _next_prod(stack)
                    continue
                # cur_symbol is non-terminal. May need to go deeper
                if cur_symbol_id > 0:
                    prev_symbol = cur_prod.production[cur_symbol_id-1]
                    prev_symbol_is_nullable = prev_symbol in nullables
                else:
                    prev_symbol_is_nullable = True

                if not prev_symbol_is_nullable:
                    # do not check current symbol because previous not nullable
                    _next_prod(stack)
                    continue

                # do need to go deeper
                stack.append([cur_symbol, self.prods_map[cur_symbol], 0, 0])

    def _log_cur_prod(self, parse_stack, tokens):
        # log current production
        top = parse_stack[-1]
        prefix = "  "*top.log_offset
        if top.cur_prod_id == 0:
            self._log_debug(
                prefix + "try match '%s': (next token #%s) %s)",
                parse_stack[-1].symbol, top.start_token_pos,
                tokens[top.start_token_pos])
        self._log_debug(
            prefix + "- (%s/%s) %s",
            top.cur_prod_id+1, len(top.prod_rs), top.get_cur_prod())

    def _log_match_result(self, parse_stack, tokens):
        # log result of the match
        top = parse_stack[-1]
        prefix = "  "*top.log_offset
        cur_prod = top.get_cur_prod()
        is_success = len(top.values) == len(cur_prod.production)
        if is_success:
            self._log_debug(prefix + "'%s' matched", top.symbol)
        else:
            failed_symbol = cur_prod.production[len(top.values)]
            failed_token = tokens[top.cur_token_pos]
            self._log_debug(
                prefix + "'%s' desn't match. Prod symbol '%s' doesn't match '%s'",
                top.symbol,
                failed_symbol, failed_token)

    def _log_debug(self, *args, **kwargs):
        logger.error(*args, **kwargs)

    def _process_seq_telement(self, t_elem):
        # helper of 'parse' method.
        # immediately process (cleanup) TElement which corresponds
        # to 'ProdSequence' production.
        assert t_elem.name in self._seq_symbols

        if t_elem.value is None:
            # end of the sequence
            seq = []
        else:
            # t_elem corresponds to a production which looks like
            # ('SEQUENCE_ITEM', 'SEQUENCE_TAIL')
            #
            # The 'SEQUENCE_TAIL' child element is already processed and
            # contains the list of elements of the tail of sequence
            assert len(t_elem.value) == 2

            assert t_elem.value[1].name == t_elem.name
            seq = t_elem.value[1].value

            next_item = t_elem.value[0]
            assert isinstance(next_item, TElement)
            assert len(next_item.value) == 1
            next_val = next_item.value[0]
            seq.insert(0, next_val)

        t_elem.value = seq
        t_elem._is_leaf = True

    @classmethod
    def _make_llone_table(cls, prods_map, terminals, nullables, start_symbol_name):
        """Make Parsing Table.

        Returns possible productions for non-terminal-symbol and next token:
            {(non_term_symbol, next_token): [production, ]}
        """
        first_sets = cls._calc_first_sets(prods_map, terminals, nullables)
        follow_sets = cls._calc_follow_sets(
            prods_map, terminals, nullables, first_sets, start_symbol_name)

        parse_table = defaultdict(list)
        for non_term, prod_rs in prods_map.items():
            for prod_rule in prod_rs:
                start_symbols = set()
                for symbol in prod_rule.production:
                    if symbol is None:
                        assert len(prod_rule.production) == 1
                        continue
                    if symbol in terminals:
                        start_symbols.add(symbol)
                        break
                    # symbol is non-terminal
                    start_symbols |= first_sets[symbol]
                    if symbol not in nullables:
                        break
                else:
                    # all the symbols in production are nullable
                    assert non_term in nullables
                    start_symbols |= follow_sets[non_term]

                for first_symbol in start_symbols:
                    parse_table[(non_term, first_symbol)].append(prod_rule)

        for prod_rs in parse_table.values():
            prod_rs.sort(key=lambda r: r.sort_n)

        return parse_table, first_sets, follow_sets

    @classmethod
    def _calc_follow_sets(
        cls, prods_map, terminals, nullables, first_sets, start_symbol_name,
    ):
        """Calculate 'follow-sets'

        {'NON_TERM': set(t| S ->* b NON_TERM t XXX)}
        """
        assert start_symbol_name in prods_map, (
            f"invalid grammar: there are no productions for "
            f"start symbol '{start_symbol_name}'")

        follow_sets = {non_term: set() for non_term in prods_map.keys()}
        follow_sets[start_symbol_name].add(cls._END_TOKEN_NAME)

        # follows dependencies rules: follow set for a symbol must include
        # follow sets of all the dependent symbols
        follows_deps = {non_term: set() for non_term in prods_map.keys()}

        # 1. calculate 'immediate follows' - cases when non-terminal symbol
        # is followed by terminal or non-terminal in some production
        for non_term, prod_rs in sorted(prods_map.items()):
            for prod_r in prod_rs:
                for i, cur_symbol in enumerate(prod_r.production):
                    if cur_symbol in terminals:
                        continue
                    for next_symbol in prod_r.production[i+1:]:
                        if next_symbol in terminals:
                            follow_sets[cur_symbol].add(next_symbol)
                        else:
                            follow_sets[cur_symbol].update(first_sets[next_symbol])
                            if next_symbol in nullables:
                                follows_deps[cur_symbol].add(next_symbol)
                        if next_symbol not in nullables:
                            break
                    else:
                        # all the symbols after cur_symbol are nullable
                        # so, any token which can follow top-level non_term
                        # may follow cur_symbol as well
                        follows_deps[cur_symbol].add(non_term)

        # 2. finalize follow_sets
        while True:
            sets_updated = False
            for symbol, depends in follows_deps.items():
                follow_set = follow_sets[symbol]
                orig_len = len(follow_set)
                for dep in depends:
                    follow_set.update(follow_sets[dep])
                sets_updated |= len(follow_set) != orig_len
            if not sets_updated:
                break

        return follow_sets

    @staticmethod
    def _get_nullables(prods_map):
        # get set of all nullable symbols
        cur_set = set([None, ])  # temporary, None will not be in final result
        next_set = set()
        while len(cur_set) != len(next_set):
            next_set.update(cur_set)
            for non_term, prod_rs in prods_map.items():
                if non_term in next_set:
                    continue
                if any(
                    all(s in cur_set for s in prod_r.production)
                    for prod_r in prod_rs
                ):
                    next_set.add(non_term)
            cur_set, next_set = next_set, cur_set
        cur_set.remove(None)
        return cur_set

    def print_detailed_descr(self):
        """Print detailed description of the parser."""
        for s in self._summary.gen_detailed_descr():
            print(s)

    @classmethod
    def _calc_first_sets(cls, prods_map, terminals, nullables):
        # for each symbol get list of tokens it's production can start from
        #
        # {NON_TERM: {t| NON_TERM ->* tXXX}}
        non_terms = set(prods_map.keys())

        fsets = {t: set() for t in non_terms}

        while True:
            fsets_updated = False
            for non_term, cur_fset in fsets.items():
                for prod_r in prods_map[non_term]:
                    for symbol in prod_r.production:
                        if symbol in terminals:
                            if symbol not in cur_fset:
                                cur_fset.add(symbol)
                                fsets_updated = True
                        else:
                            # this is non-terminal symbol
                            orig_size = len(cur_fset)
                            cur_fset.update(fsets[symbol])
                            fsets_updated |= len(cur_fset) != orig_size
                        if symbol not in nullables:
                            break
            if not fsets_updated:
                break

        return fsets

    @classmethod
    def _create_productions(cls, prods_init_data, terminals, parser_summary):
        # constructor helper.
        # create ProdRule objects from productions data specified in constructor

        _sort_n_gen = itertools.count()

        prods_map = {}  # {symbol: [ProdRule, ]}
        seq_symbols = set()
        prod_templates = {}  # {symbol: ProdsTemplate}

        def _gen_prods_data():
            # internal helper, expands ProdsTemplate objects
            for symbol, productions in prods_init_data.items():
                assert '__' not in symbol, (
                    f"Invalid production symbol '{symbol}'. Symbol names containing "
                    f"'__' are reserved")

                if isinstance(productions, ProdsTemplate):
                    prods_template = productions
                    prods_template.complete_init(symbol, terminals, parser_summary)

                    yield from prods_template.gen_productions()

                    if isinstance(productions, ProdSequence):
                        seq_symbols.add(symbol)

                    if prods_template.CAN_POST_PROCESS_TELEM:
                        prod_templates[symbol] = prods_template

                    continue

                assert isinstance(productions, list)
                yield symbol, productions

        for symbol, productions in _gen_prods_data():
            for prod in productions:
                # detect incorrect productions like: "SYMBOL" -> "OTHER"
                # Should be: "SYMBOL" -> ("OTHER", )
                assert not isinstance(prod, str), (
                    f"invalid production {symbol} -> '{prod}'. "
                    f"(result should be tuple, not string)")

            assert symbol not in prods_map, (
                f"{symbol} already in {prods_map}")

            prods_map[symbol] = cls._make_prod_rules_list(
                symbol, productions, terminals, _sort_n_gen, parser_summary)

        return prods_map, seq_symbols, prod_templates

    @classmethod
    def _factorize_productions(cls, prods_map, terminals, smart_factorization):
        # transform the grammar represented by 'prods_map' by factoring out
        # common prefixes of some productions into separate productions.
        result_rules = {}
        suffix_symbols = set()

        for symbol, prod_rules in prods_map.items():
            for s, rr in cls._factorize_prods_list(
                symbol, prod_rules, suffix_symbols,
            ):
                assert s not in result_rules
                result_rules[s] = rr

        # roll-back some factorizations. This will make parsing less efficient
        # (need to measure), but will make grammar simpler.
        if smart_factorization:
            suffixes_to_remove = set()
            for symbol, rr in sorted(
                result_rules.items(), key=lambda kv: -len(kv[0])
            ):
                # rules are sorted by length. This is to make sure that
                # 'suffix' symbols are processed before corresponding parent.
                new_rules = []
                for prod_rule in rr:
                    if len(prod_rule.production) != 2:
                        new_rules.append(prod_rule)
                        continue
                    first_symbol = prod_rule.production[0]
                    if first_symbol not in terminals:
                        new_rules.append(prod_rule)
                        continue
                    last_symbol = prod_rule.production[1]
                    if last_symbol not in suffix_symbols:
                        new_rules.append(prod_rule)
                        continue
                    suffix_productions = result_rules[last_symbol]
                    if len(suffix_productions) > 5:
                        new_rules.append(prod_rule)
                        continue

                    for suffix_rule in suffix_productions:
                        new_rules.append(
                            tuple([first_symbol] + list(suffix_rule.production))
                        )
                    suffixes_to_remove.add(last_symbol)

                if len(rr) != len(new_rules):
                    final_new_rules = []
                    for i, r in enumerate(new_rules):
                        if isinstance(r, ProdRule):
                            final_new_rules.append(ProdRule(symbol, r.production, i))
                        else:
                            final_new_rules.append(ProdRule(symbol, r, i))
                    rr[:] = final_new_rules

            for s in suffixes_to_remove:
                del result_rules[s]
                suffix_symbols.remove(s)

        return result_rules, suffix_symbols

    @classmethod
    def _factorize_prods_list(cls, symbol, prod_rules, suffix_symbols):
        # factorize (combine productions with common prefix) all the productions
        # of a given symbol
        #
        # yield (symbol, [ProdRule, ]) for original symbol and all 'auxiliary'
        # symbols created during factorization process

        result_rules_list = []  # [ProdRule, ]
        suffix_prods = []  # [(symbol, [ProdRule, ]]

        _grp_id_gen = itertools.count()

        for chunk in cls._split_prods_rules(prod_rules):
            # chunk is a list of ProdRule with common prefix
            if len(chunk) == 1:
                result_rules_list.append(chunk[0])
            else:
                assert len(chunk) > 0
                group_production, extra_prods = cls._factorize_common_prefix_prods(
                    symbol, next(_grp_id_gen), chunk, suffix_symbols)
                for s, rr in extra_prods.items():
                    # yield s, rr <- yield suffix symbols later, for prettier result
                    # TODO: do not use the accumulator suffix_prods after proper
                    # sorting of map symbols is implemented
                    suffix_prods.append((s, rr))
                result_rules_list.append(group_production)

        yield symbol, result_rules_list
        yield from suffix_prods

    @classmethod
    def _split_prods_rules(cls, prod_rules):
        # helper method used during factorization process
        #
        # split list of ProdRule into chunks with same starting symbol
        cur_start_symbol = None
        cur_chunk = []
        for r in prod_rules:
            start_symbol = r.production[0] if r.production else None
            if start_symbol != cur_start_symbol:
                if cur_chunk:
                    yield cur_chunk
                    cur_chunk = []
                    cur_start_symbol = None

            cur_chunk.append(r)
            cur_start_symbol = start_symbol

        if cur_chunk:
            yield cur_chunk

    @classmethod
    def _factorize_common_prefix_prods(
        cls, symbol, group_id, prods_chunk, suffix_symbols,
    ):
        # H -> (A, B, C, D)    => H -> (A, B, H__S0x) ;  H__S0x -> (C, D)
        #   -> (A, B, X, Y)                                     -> (X, Y)
        #   -> (A, B, Z)                                        -> (Z, )

        assert len(prods_chunk) > 1

        # get common prefix
        max_len = min(len(r.production) for r in prods_chunk)
        common_prefix = list(prods_chunk[0].production[:max_len])
        for prod_rule in prods_chunk[1:]:
            for i, (s1, s2) in enumerate(zip(common_prefix, prod_rule.production)):
                if s1 != s2:
                    common_prefix = common_prefix[:i]
                    break
        assert len(common_prefix) > 0, (
            "empty common prefix:\n" + "\n".join(str(r) for r in prods_chunk))

        grp_symbol_suffix = f"{symbol}__S{group_id:02}"

        # make single production for 'symbol': H -> (A, B, H__S0x)
        # common_prefix + grp_symbol_suffix
        group_prod_rule = ProdRule(
            symbol,
            tuple(list(common_prefix) + [grp_symbol_suffix]),
            prods_chunk[0].sort_n)

        # make productions for the suffix
        suff_prods_counter = itertools.count()
        suffix_prod_rules = [
            ProdRule(
                grp_symbol_suffix,
                tuple(orig_prod_rule.production[len(common_prefix):]),
                next(suff_prods_counter),
            )
            for orig_prod_rule in prods_chunk
        ]
        assert grp_symbol_suffix not in suffix_symbols
        suffix_symbols.add(grp_symbol_suffix)

        aux_symbols_prod_rules = dict( # {symbol: [ProdRule, ]}
            cls._factorize_prods_list(
                grp_symbol_suffix, suffix_prod_rules, suffix_symbols)
        )

        return group_prod_rule, aux_symbols_prod_rules

    @staticmethod
    def _make_prod_rules_list(
        symbol, productions, terminals, sort_n_gen, parser_summary,
    ):
        # Constructor helper. Creates list of ProdRule objects from the
        # productions data specified as consctructor argument.
        #
        # Provided productions data is almost ready, non-trivial processing
        # is required for 'AnyTokenExcept' pseudo-production only
        result = []
        special_token_encountered = False
        for production in productions:
            if production is None:
                result.append(ProdRule(symbol, (), next(sort_n_gen)))
            elif isinstance(production, tuple):
                result.append(ProdRule(symbol, production, next(sort_n_gen)))
            elif isinstance(production, list):
                raise GrammarError(
                    parser_summary,
                    f"invalid production: {production}. "
                    f"It must be a tuple, not a list")
            elif isinstance(production, AnyTokenExcept):
                if special_token_encountered:
                    raise GrammarError(
                        parser_summary,
                        f"productions for symbol '{symbol}' contain several "
                        f"elemens of type 'AnyTokenExcept'. Only one such "
                        f"element is allowed")
                special_token_encountered = True
                for t in production.get_tokens(terminals, symbol, parser_summary):
                    result.append(
                        ProdRule(symbol, (t, ), next(sort_n_gen))
                    )

        return result


#########################
# Cleanuper

# TODO: make base class
#    LLParser produces a tree of TElement objects.
#    This tree usually contains too many elements, corresponding to

class StdCleanuper:
    """Default Cleanuper, used by LLParser for post-processing parse results.

    Converts TElement sutrees corresponding to ListProds and MapProds into
    lists and dictionaries.
    Makes the result tree more compact by removing some elements, which do
    not contain 'useful' information.
    TODO: try to descibe cleanup rules.
    """

    def __init__(self, prod_templates, choice_symbols, keep_symbols, squash_symbols):
        self.prod_templates = prod_templates
        self.choice_symbols = choice_symbols
        self.keep_symbols = keep_symbols
        self.squash_symbols = squash_symbols

    @classmethod
    def make(cls, llparser: LLParser, keep_symbols) -> Self:

        keep_symbols = set() if keep_symbols is None else keep_symbols
        keep_symbols.add(llparser.start_symbol_name)

        squash_symbols, choice_symbols = cls._make_squash_data(llparser)

        return StdCleanuper(
            llparser.prod_templates, choice_symbols, keep_symbols, squash_symbols)

    @classmethod
    def _make_squash_data(cls, llparser: LLParser):
        # prepare information about potentially squashable symbols
        # (part of clenup procedure)
        #
        # Method returns:
        # - squash_symbols: symbols which can potentially be "squashed"
        # - choice_symbols: symbols which have only zero- or one-value productions

        squash_symbols = set()
        choice_symbols = set()

        for symbol, prod_rules in llparser.prods_map.items():
            if symbol in llparser._suffix_symbols:
                continue
            n_null_prods = sum(
                1 if len(r.production) == 0 else 0
                for r in prod_rules)
            n_oneval_prods = sum(
                1 if len(r.production) == 1 else 0
                for r in prod_rules)
            if n_null_prods + n_oneval_prods < len(prod_rules):
                # there are more complex productions, no squash is possible
                continue

            squash_symbols.add(symbol)
            if n_oneval_prods > 1:
                choice_symbols.add(symbol)

        return squash_symbols, choice_symbols

    def gen_detailed_descr(self):
        yield f"  keep_symbols: {sorted(self.keep_symbols)}"
        yield f"  choice_symbols: {sorted(self.choice_symbols)}"
        yield f"  squash_symbols: {sorted(self.squash_symbols)}"
        if self.prod_templates is None:
            yield f"  Prod Templates: <n/a>"
        else:
            yield f"  Prod Templates:"
            for _, prod_template in sorted(self.prod_templates.items()):
                yield f"    - {prod_template}"

    def cleanup(self, t_elem: TElement) -> None:
        """Transform TElement subtree according to own rules."""
        self._cleanup(t_elem)

    def _cleanup(
            self, t_elem: TElement,
            for_container: bool = False, for_choice: bool = False,
        ) -> bool:
        # internal helper to be used during cleanup.
        #
        # returns 'elem_no_squash' - bool, which tells parent TElement if
        # this element can be squashed

        elem_no_squash = for_choice

        if t_elem.name in self.prod_templates:
            # process lists and maps templates
            self.prod_templates[t_elem.name].transform_t_elem(t_elem, self)
            return elem_no_squash

        if t_elem.is_leaf():
            return elem_no_squash

        values = []
        values_no_squash = []
        for child_elem in t_elem.value:
            if child_elem is None:
                # TODO: remove the if completely
                assert False, "I guess it should not ever happen"
                continue
            child_no_squash = self._cleanup(
                child_elem,
                for_choice = t_elem.name in self.choice_symbols,
            )

            values.append(child_elem)
            values_no_squash.append(child_no_squash)

        if not values:
            t_elem.value = None
            return elem_no_squash

        t_elem.value = values

        if_squash = t_elem.name in self.squash_symbols

        if if_squash:
            assert isinstance(t_elem.value, list)
            assert len(t_elem.value) == 1, f"{t_elem.name=} {t_elem.value=}"
            assert len(t_elem.value) == len(values_no_squash)
            child_elem = t_elem.value[0]
            child_no_squash = values_no_squash[0]
            assert isinstance(child_elem, TElement)

            keep_parent = for_choice or t_elem.name in self.keep_symbols
            keep_child = child_no_squash or child_elem.name in self.keep_symbols

            if keep_parent and keep_child:
                if_squash = False
                elem_no_squash = True
            else:
                squash_parent = keep_child or for_container

        if if_squash:
            if squash_parent:
                elem_no_squash = child_no_squash
                t_elem.name = child_elem.name
                t_elem.value = child_elem.value
                t_elem._is_leaf = child_elem._is_leaf
            else:
                elem_no_squash = keep_parent
                t_elem.value = child_elem.value
                t_elem._is_leaf = child_elem._is_leaf

        return elem_no_squash
