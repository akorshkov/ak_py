r"""LL1 parser with some ambiguities handling.

1. Main difference from LL1 parser is that it allowes ambiguities.
Parsing table may contain several matching productions for a pair:
(SYMBOL, next_token) -> (A, B, C)
                        (X, Y, Z)
If matching process fails for the first production, parsing process will
roll back and next production will be attempted. First successfully
matched production will be used.

So, it is possible to use following productions for symbol 'A':
A: [
    (X, Y, Z),
    (X, Y),
]

2. Second difference is that if for some symbol there are several consequtive
productions with same prefix, grammar will be automatically transformed:
A: [                  =>  A: [                  A__S00: [
    (X, Y, A, B),     =>      (X, Y, A__S00),       (A, B),
    (X, Y, C, D),     =>  ]                         (C, D),
]                                               ]
This transformation may remove ambiguities.

Example of usage:

parser = LLParser(
    r'''
    (?P<SPACE>\s+)
    |(?P<WORD>[a-zA-Z_][a-zA-Z0-9_]*)
    |(?P<NUMBER>[0-9]+)
    |(?P<BR_OPEN>\[)
    |(?P<BR_CLOSE>\])
    ''',
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

x = parser.parse("[a b c] 10")  # TElement
print(str(x))
"""

import re
from collections import defaultdict
import collections.abc
from dataclasses import dataclass
import itertools
from typing import Tuple, NamedTuple, Self
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
    pass


class GrammarIsRecursive(GrammarError):
    """Grammar is recursive.

    Means that when we expand some symbol X we can come to situation when no
    tokens consumed, but the next symbol to expand is the same symbol X.
    """
    def __init__(self, cycle_data, nullables):
        msg = f"grammar is recursive:\n{nullables=}\n" + "\n".join(
            self._mk_prod_descr(cycle_element)
            for cycle_element in cycle_data
        )
        super().__init__(msg)

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
                    f"unknows opening symbol '{open_token_name}' specified "
                    f"in 'span_matchers'. Each key of this dict must be a "
                    f"name of the re group specified in tokenizer scrting")
            result[open_token_name] = re.compile(re_str, re.VERBOSE)
        return result


class TElementCleanupRules_Old:
    """Rules for transforming TElement tree.

    Results of the parsing are presented in a form of a tree of TElement.
    The tree can be simplified (for example, subtree corresponding to a list
    can be substituted with actual list). This object contains rules of
    such transformations.
    """

    def __init__(
            self, *,
            keep_symbols=None, lists=None, maps=None,
            squash_symbols=None, choice_symbols=None,
        ):
        self.keep_symbols = set() if keep_symbols is None else keep_symbols
        self.lists = lists if lists is not None else {}
        self.maps = maps if maps is not None else {}

        self.squash_symbols = set() if squash_symbols is None else squash_symbols
        self.choice_symbols = set() if choice_symbols is None else choice_symbols

    def gen_detailed_descr(self):
        yield f"keep_symbols: {self.keep_symbols}"
        yield f"Lists:"
        if self.lists:
            for list_rules in self.lists:
                yield f"  {list_rules}"
        else:
            yield f" --"
        yield f"Maps:"
        if self.maps:
            for map_rules in self.maps:
                yield f"  {map_rules}"
        else:
            yield f" --"
        yield f"squash symbols: {sorted(self.squash_symbols)}"
        yield f"choice symbols: {sorted(self.choice_symbols)}"

    def verify_integrity(self, terminals, non_terminals):
        """Verify correctness of rules."""

        for s in self.keep_symbols:
            if s not in terminals and s not in non_terminals:
                raise GrammarError(
                    f"unknown symbol '{s}' specified in {self.keep_symbols=}")

        for s in self.squash_symbols:
            if s not in terminals and s not in non_terminals:
                raise GrammarError(
                    f"unknown symbol '{s}' specified in {self.squash_symbols=}")

        for s in self.choice_symbols:
            if s not in terminals and s not in non_terminals:
                raise GrammarError(
                    f"unknown symbol '{s}' specified in {self.choice_symbols=}")

        def _verify_is_terminal(symbol, allow_none=False, descr="symbol"):
            if symbol in terminals:
                return
            if symbol is None and allow_none:
                return
            if symbol in non_terminals:
                raise GrammarError(f"{descr} '{symbol}' is non-terminal symbol")
            raise GrammarError(f"{descr} '{symbol}' is unknown")

        def _verify_is_non_terminal(symbol, descr="symbol"):
            if symbol in non_terminals:
                return
            if symbol in terminals:
                raise GrammarError(f"{descr} '{symbol}' is terminal")
            raise GrammarError(f"{descr} '{symbol}' is unknown")

        for list_symbol, properties in self.lists.items():
            if len(properties) != 4:
                raise GrammarError(
                    f"invalid cleanup rules for list symbol "
                    f"'{list_symbol}': {properties}. \n"
                    f"Expected tuple: "
                    f"(open_br, delimiter, tail_symbol, close_br)")
            open_br, delimiter, tail_symbol, close_br = properties
            _verify_is_non_terminal(list_symbol, "list symbol")
            _verify_is_non_terminal(tail_symbol, "list tail symbol")
            _verify_is_terminal(delimiter, True, "list delimiter symbol")
            if open_br is not None:
                if close_br is None:
                    raise GrammarError(
                        f"list open symbol '{open_br}' is not None, "
                        f"but close symbol is None")
            else:
                if close_br is not None:
                    raise GrammarError(
                        f"list open symbol is None, "
                        f"but close symbol '{close_br}' is not None")
            _verify_is_terminal(open_br, "list open symbol")
            _verify_is_terminal(close_br, "list close symbol")

        for map_symbol, properties in self.maps.items():
            if len(properties) != 6:
                raise GrammarError(
                    f"invalid cleanup rules for map symbol "
                    f"'{map_symbol}': {properties}. \n"
                    f"Expected tuple: "
                    f"(open_br, map_elements_name, items_delimiter, "
                    f"map_element_name, delimiter, close_br)"
                )
            (
                open_br,
                map_elements_name,
                items_delimiter,
                map_element_name,
                delimiter,
                close_br
            ) = properties
            _verify_is_non_terminal(map_elements_name, "map symbol")
            _verify_is_non_terminal(map_element_name, "map element symbol")
            _verify_is_terminal(open_br, "map open symbol")
            _verify_is_terminal(close_br, "map close symbol")
            _verify_is_terminal(items_delimiter, "map items_delimiter symbol")
            _verify_is_terminal(delimiter, "map delimiter symbol")
            if open_br is not None:
                if close_br is None:
                    raise GrammarError(
                        f"map open symbol '{open_br}' is not None, "
                        f"but close symbol is None")
            else:
                if close_br is not None:
                    raise GrammarError(
                        f"map open symbol is None, "
                        f"but close symbol '{close_br}' is not None")

@dataclass(frozen=True)
class TElemSignature:
    """!!!"""
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

        #signature = [self.name]
        #if not self.is_leaf():
        #    signature.extend(
        #        x.name if x is not None else None
        #        for x in self.value
        #    )
        #return tuple(signature)

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
        if t_elem is None:
            return default
        return t_elem.value

#    def cleanup(
#        self, rules=None, *,
#        keep_symbols=None, lists=None, maps=None,
#        _for_container=False,
#        _for_choice=False,
#    ):
#
#    def _cleanup(self, rules, _for_container=False, _for_choice=False) -> bool:
#        # do all the work of cleanup method
#        #
#        # returns 'elem_no_squash' - bool, which tells parent TElement if
#        # this element can be squashed
#
#        elem_no_squash = _for_choice
#
#        if self.name in rules.lists:
#            self.reduce_list(rules, rules.lists[self.name])
#            return elem_no_squash
#        elif self.name in rules.maps:
#            self.reduce_map(rules, rules.maps[self.name])
#            return elem_no_squash
#
#        if self.is_leaf():
#            return elem_no_squash
#
#        values = []
#        values_no_squash = []
#        for child_elem in self.value:
#            if child_elem is None:
#                continue
#            assert hasattr(child_elem, '_cleanup'), (
#                f"{self=} {self._is_leaf=} {self.value=}")
#            child_no_squash = child_elem._cleanup(
#                rules,
#                _for_choice = self.name in rules.choice_symbols
#            )
#            if child_elem.value is not None or child_elem.name in rules.keep_symbols:
#                values.append(child_elem)
#                values_no_squash.append(child_no_squash)
#
#        if not values:
#            self.value = None
#            return elem_no_squash
#
#        self.value = values
#
#        if_squash = self.name in rules.squash_symbols
#
#        if if_squash:
#            assert isinstance(self.value, list)
#            assert len(self.value) == 1, f"{self.name=} {self.value=}"
#            assert len(self.value) == len(values_no_squash)
#            child_elem = self.value[0]
#            child_no_squash = values_no_squash[0]
#            assert isinstance(child_elem, TElement)
#
#            keep_parent = _for_choice or self.name in rules.keep_symbols
#            keep_child = child_no_squash or child_elem.name in rules.keep_symbols
#
#            if keep_parent and keep_child:
#                if_squash = False
#                elem_no_squash = True
#            else:
#                squash_parent = keep_child or _for_container
#
#        if if_squash:
#            if squash_parent:
#                elem_no_squash = child_no_squash
#                self.name = child_elem.name
#                self.value = child_elem.value
#                self._is_leaf = child_elem._is_leaf
#            else:
#                elem_no_squash = keep_parent
#                self.value = child_elem.value
#                self._is_leaf = child_elem._is_leaf
#
#        return elem_no_squash


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
    """!!! """
    CAN_POST_PROCESS_TELEM = True

    def __init__(self):
        self.result_symbol = None

    def _ensure_initialized(self):
        assert self.result_symbol is not None, (
            f"{self} is not initialized. Call 'complete_init' "
            f"method to complete initialzation")

    def complete_init(self, result_symbol: str) -> None:
        """!!!"""
        assert self.result_symbol is None, (
            f"{self} is already initialized (with result symbol "
            f"'{self.result_symbol}')")
        self.result_symbol = result_symbol

#    def get_used_tokens(self):
#        """!!!"""
#        assert False, f"not implemented in {str(type(self))}"
#
#    def get_used_symbols(self):
#        """!!!"""
#        assert False, f"not implemented in {str(type(self))}"

    def verify_grammar(self, llparser, nullables):
        pass

    def gen_productions(self):
        assert False, f"not implemented in {str(type(self))}"
        yield from []

    @staticmethod
    def _find_index(symbols_list, symbol):
        # !!!!!!
        try:
            i = symbols_list.index(symbol)
        except ValueError:
            i = None
        return i


class ProdSequence(ProdsTemplate):
    """Production which matches a sequence of elements.

        !!!!!!
    """
    CAN_POST_PROCESS_TELEM = False

    def __init__(self, *symbols):
        self.symbols = list(symbols)
        self.element_symbol_name = None

    def complete_init(self, result_symbol) -> None:
        assert result_symbol is not None
        super().complete_init(result_symbol)
        assert self.result_symbol is not None

        self.element_symbol_name = f"{self.result_symbol}__ELEMENT"

    def gen_productions(self):
        """!!!!"""
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
    """!!!

    'LIST_PROD': ListProds('[', 'LIST_ITEM', ',', ']', allow_final_delimiter=False)

    """
    def __init__(
        self,
        open_br: str, item_symbol: str, sep_token: str, close_br: str, *,
        allow_final_delimiter=None,
        optional=None,
    ):
        assert (open_br is None) == (close_br is None), (
            f"'open_br' and 'close_br' can be None only simultaneously: "
            f"{open_br=}; {close_br=}")

        if allow_final_delimiter is None:
            allow_final_delimiter = sep_token is not None and open_br is not None

        if allow_final_delimiter:
            assert sep_token is not None and open_br is not None, (
                f"In ListProd for '{item_symbol}': allow_final_delimiter can "
                f"be True only if open_br, close_br and sep_token are not None")

        if optional is not None:
            assert open_br is not None, (
                f"'optional' argument is implemented only for lists with brackets")
        else:
            optional = False

        super().__init__()

        self.open_br = open_br
        self.item_symbol = item_symbol
        self.sep_token = sep_token
        self.close_br = close_br
        self.allow_final_delimiter = allow_final_delimiter
        self.optional = optional

        self.list_tail_symbol = None
        self.list_prods_signatures = None
        self.tail_prods_signatures = None

    def complete_init(self, result_symbol) -> None:
        assert result_symbol is not None
        super().complete_init(result_symbol)
        assert self.result_symbol is not None

        has_brackets = self.open_br is not None
        has_separator = self.sep_token is not None

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
            # !!!!!!
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
                [self.sep_token, self.item_symbol, self.list_tail_symbol],
                [self.sep_token, ],
                [],
            ]
            if not self.allow_final_delimiter:
                list_tail_prods.pop(1)

        # now list_prods and list_tail_prods contain names of symbols
        # for LIST and LIST__TAIL productions. But these lists
        # may contain None values in place of sep_token.
        # Following methods will purge these extra items.

        self.list_prods_signatures = dict(
            self._make_expected_signature(self.result_symbol, prod)
            for prod in list_prods
        )
        self.tail_prods_signatures = dict(
            self._make_expected_signature(self.list_tail_symbol, prod)
            for prod in list_tail_prods
        )

    def verify_grammar(self, llparser, nullables):
        if self.sep_token is None and self.item_symbol in nullables:
            raise GrammarError(
                f"List item symbol '{self.item_symbol}' is nullable. "
                f"It is prohibited for lists without separator symbol.")

    def _make_expected_signature(self, symbol, prod_symbols):
        # !!!!!!!!
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
        sep = "" if self.sep_token is None else self.sep_token
        return f"{str(type(self))}<{result} -> {op}{item}{sep}...{cl}>"

    def gen_productions(self):
        """!!!!"""
        self._ensure_initialized()
        has_brackets = self.open_br is not None
        has_separator = self.sep_token is not None

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
        """!!!"""
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

        # new_values now contains TElement objects and Nones.
        # If some TElement is a leaf - replace it with it's value
        # ??????
        # can it really contain None?????   !!!!!
        values_list = [
            x.value if isinstance(x, TElement) and x.is_leaf() else x
            for x in values_list
        ]

        if (
            len(values_list) > 0
            and values_list[-1] is None
            and self.allow_final_delimiter
        ):
            # !!!!!!
            assert self.sep_token is not None # !!!!! just interesting
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
        # !!!!!!
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
    """ !!! """

    def __init__(
        self, open_br: str,
        key_symbol: str, assign_symbol: str, val_symbol: str,
        sep_token: str, close_br: str, *,
        optional=None,
    ):
        assert (open_br is None) == (close_br is None), (
            f"'open_br' and 'close_br' can be None only simultaneously: "
            f"{open_br=}; {close_br=}")

        assert assign_symbol is not None
        assert sep_token is not None

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
        self.sep_token = sep_token
        self.close_br = close_br
        self.optional = optional

        self.kv_pair_symbol = None
        self.kv_tail_symbol = None

        self.map_prods_signatures = None
        self.kv_tail_prods_signatures = None
        self.kv_prod_signature = None

    def complete_init(self, result_symbol) -> None:
        assert result_symbol is not None
        super().complete_init(result_symbol)
        assert self.result_symbol is not None

        has_brackets = self.open_br is not None

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
            [self.sep_token, self.kv_pair_symbol, self.kv_tail_symbol],
            [self.sep_token, ],
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
        self.kv_prod_signature = TElemSignature(self.kv_pair_symbol, kv_prod)

    def _make_expected_signature(self, symbol, prod_symbols):
        # !!!!!!
        prod_symbols = tuple(s for s in prod_symbols if s is not None)

        signature = TElemSignature(symbol, prod_symbols)
        positions = (
            self._find_index(prod_symbols, self.kv_pair_symbol),
            self._find_index(prod_symbols, self.kv_tail_symbol),
        )
        return signature, positions

    def transform_t_elem(self, t_elem: TElement, cleanuper) -> None:
        """!!!"""
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
        # !!!!!!
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
        # !!!!!!!
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
    """Contains information about LLParser.

    It is used for reporting purposes only.
    Main purpose of this class is to keep information about LLParser
    even if the LLParser was not created. Some grammar errors may be raised
    during LLParser consctruction, but to properly report these problems
    it's good to have all all the processed data structures.
    """

    def __init__(
            self, terminals, orig_prods_map, prods_map, parse_table,
            nullables, first_sest, follow_sets,
            cleanuper,
        ):
        self.terminals = terminals
        self.orig_prods_map = orig_prods_map
        self.prods_map = prods_map
        self.parse_table = parse_table
        self.nullables = nullables
        self.first_sest = first_sest
        self.follow_sets = follow_sets
        self.cleanuper = cleanuper

    def gen_detailed_descr(self):
        """Generate lines of human-readable description of the LLParser."""
        mk_descr_len = lambda x, size: f"'{x}'" + " "*(max(0, size - len(str(x))))

        yield "= Parser summary ="
        yield ""
        yield f"Terminals: {self.terminals}"
        yield ""
        yield from self._descr_prods_map("Original Productions", self.orig_prods_map)
        yield ""
        yield from self._descr_prods_map("Factorized Productions", self.prods_map)
        yield ""
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
        yield f"Nullables: {self.nullables}"
        not_nullables = self.prods_map.keys() - self.nullables
        yield f"Not Nullables: {not_nullables}"
        yield ""
        yield "FirstSets:"
        for symbol, firsts in sorted(self.first_sest.items()):
            yield f"    {mk_descr_len(symbol, 10)}: {sorted(firsts)}"
        yield ""
        yield "FollowSets:"
        for symbol, follows in sorted(self.follow_sets.items()):
            yield f"    {mk_descr_len(symbol, 10)}: {sorted(follows)}"
        yield ""
        yield "Cleanup Rules:"
        yield from self.cleanuper.gen_detailed_descr()

    def _descr_prods_map(self, map_name, prods_map):
        yield f"{map_name}:"
        for symbol, prod_rs in prods_map.items():
            yield ""
            # yield f"    '{symbol}':"
            for rule in prod_rs:
                yield f"    {rule}"



class LLParser:
    """LLParser. Mostly LL1, but can deal with ambiguities in LL1 parsing table."""

    _END_TOKEN_NAME = '$END$'
    _INIT_PRODUCTION_NAME = '$START$'

    ProdSequence = ProdSequence
    AnyTokenExcept = AnyTokenExcept
    ListProds = ListProds
    MapProds = MapProds

    def __init__(
            self,
            tokenizer_str,
            *,
            productions,
            span_matchers=None,
            synonyms=None,
            keywords=None,
            skip_tokens=None,
            start_symbol_name='E',
            keep_symbols=None,
            lists=None,
            maps=None,
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
        - lists: rules for cleanup. The cleanup procedure replaces subtree
            corresponding to list with actual list of values. This argument contains
            names of tokens wich correspond to list and list elements:
                {'LIST': ('[', ',', 'OPT_LIST', ']')}
        - maps: similar to 'lists', but describes maps. Example:
                {'MAP': ('{', 'MAP_ELEMENTS', ',', 'MAP_ELEMENT', ':', '}'),}
        """
        self.tokenizer = _Tokenizer(
            tokenizer_str,
            span_matchers=span_matchers,
            synonyms=synonyms, keywords=keywords)

        self.terminals = self.tokenizer.get_all_token_names()
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
                    f"uknown token names specified in 'skip_tokens' "
                    f"arg: {unexpected}")

        self.start_symbol_name = start_symbol_name
        orig_prods_map, self._seq_symbols, self.prod_templates = (
            self._create_productions(productions, self.terminals))

        self.prods_map, self._suffix_symbols = self._factorize_productions(
            orig_prods_map, self.terminals)

        self.terminals.add(self._END_TOKEN_NAME)

        self._verify_grammar_structure_part1()

        nullables = self._get_nullables(self.prods_map)

        self.prods_map[self._INIT_PRODUCTION_NAME] = [
            ProdRule(
                self._INIT_PRODUCTION_NAME,
                (self.start_symbol_name, self._END_TOKEN_NAME, ),
                -1,
            )
        ]

#        squash_symbols, choice_symbols = self._make_squash_data(keep_symbols)
#
#        self.cleanup_rules = TElementCleanupRules_Old(
#            keep_symbols=keep_symbols,
#            squash_symbols=squash_symbols, choice_symbols=choice_symbols,
#            lists=lists,
#            maps=maps,
#        )
#        self.cleanup_rules.verify_integrity(
#            self.terminals,
#            set(self.prods_map.keys()))

        for prod_template in self.prod_templates.values():
            prod_template.verify_grammar(self, nullables)

        self.cleanuper = StdCleanuper.make(self, keep_symbols)

        self.parse_table, first_sets, follow_sets = self._make_llone_table(
            self.prods_map, self.terminals, nullables,
            self.start_symbol_name,
        )

        # used only for printing detailed description of the parser
        self._summary = ParserSummary(
            self.terminals,
            orig_prods_map,
            self.prods_map,
            self.parse_table,
            nullables,
            first_sets,
            follow_sets,
            self.cleanuper,
        )

        self._verify_grammar_structure_part2(nullables)

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
                        #self.cleanup(root)
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

#    def cleanup(self, t_element) -> None:
#        """Clean up the tree with root in t_element.
#
#        Usually the cleanup is performed in parse method, in this case there is
#        no need to repeat the cleanup. Use this method only if parse was called
#        with do_cleanup=False.
#        """
#        t_element.cleanup(
#            self.cleanup_rules,
#            _for_choice=True,  # keep root element during cleanup
#        )

    def is_ambiguous(self) -> bool:
        """Checks if grammar is LL1.
        That is there is no more than one production for (symbol, next_token) pair.
        """
        return any(len(prods) != 1 for prods in self.parse_table.values())

    def _verify_grammar_structure_part1(self):
        # initial verification of grammar structure
        # to be called before parse_table is prepared
        #
        # reports only very obvious problems. Less obvious problems
        # can be detected and/or properly reported only after parser is prepared
        if self.start_symbol_name not in self.prods_map:
            raise GrammarError(
                f"no productions for start symbol '{self.start_symbol_name}'")

        if self._END_TOKEN_NAME in self.prods_map:
            raise GrammarError(
                f"production specified for end symbol '{self._END_TOKEN_NAME}'")

        if self._INIT_PRODUCTION_NAME in self.prods_map:
            raise GrammarError(
                f"production specified explicitely for "
                f"special symbol '{self._INIT_PRODUCTION_NAME}'")

        non_terminals = set(self.prods_map.keys())
        bad_tokens = non_terminals.intersection(self.terminals)

        if bad_tokens:
            raise GrammarError(
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
                f"unexpected symbols {unknown_symbols} used in productions")

        if self._END_TOKEN_NAME in all_prod_symbols:
            raise GrammarError(
                f"special end token '{self._END_TOKEN_NAME}' is explicitely "
                f"used in productions")

        if self._INIT_PRODUCTION_NAME in all_prod_symbols:
            raise GrammarError(
                f"special start symbol '{self._INIT_PRODUCTION_NAME}' is explicitely "
                f"used in productions")

    def _verify_grammar_structure_part2(self, nullables):
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
                        raise GrammarIsRecursive(cycle_data, nullables)

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
        #prefix = "  "*(len(parse_stack) - 1)
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
        #prefix = "  "*(len(parse_stack) - 1)
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
    def _create_productions(cls, prods_init_data, terminals):
        # constructor helper.
        # create ProdRule objects from productions data specified in constructor

        _sort_n_gen = itertools.count()

        prods_map = {}  # {symbol: [ProdRule, ]}
        seq_symbols = set()
        prod_templates = {}  # {symbol: ProdsTemplate}

        def _gen_prods_data():
            # !!!!!!
            for symbol, productions in prods_init_data.items():
                assert '__' not in symbol, (
                    f"Invalid production symbol '{symbol}'. Symbol names containing "
                    f"'__' are reserved")

                if isinstance(productions, ProdsTemplate):
                    prods_template = productions
                    prods_template.complete_init(symbol)

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
                symbol, productions, terminals, _sort_n_gen)

        return prods_map, seq_symbols, prod_templates

    @classmethod
    def _factorize_productions(cls, prods_map, terminals):
        result_rules = {}
        suffix_symbols = set()

        for symbol, prod_rules in prods_map.items():
            for s, rr in cls._factorize_prods_list(
                symbol, prod_rules, suffix_symbols,
            ):
                assert s not in result_rules
                result_rules[s] = rr

        # !!!!!!! comment
        suffixes_to_remove = set()
        for symbol, rr in result_rules.items():
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
                    # suffix_symbols.add(s) !!!!!!
                    # yield s, rr <- yield later, for prettier result
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
    def _make_prod_rules_list(symbol, productions, terminals, sort_n_gen):
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
                    f"invalid production: {production}. "
                    f"It must be a tuple, not a list")
            elif isinstance(production, AnyTokenExcept):
                if special_token_encountered:
                    raise GrammarError(
                        f"productions for symbol '{symbol}' contain several "
                        f"elemens of type 'AnyTokenExcept'. Only one such "
                        f"element is allowed")
                special_token_encountered = True
                tokens_to_exclude = set(production.tokens)
                unexpected_tokens = tokens_to_exclude - terminals
                if unexpected_tokens:
                    raise GrammarError(
                        f"unknown terminal(s) specified in 'AnyTokenExcept' item "
                        f"of productions of symbol '{symbol}': {unexpected_tokens}")
                for t in terminals - tokens_to_exclude:
                    result.append(
                        ProdRule(symbol, (t, ), next(sort_n_gen))
                    )

        return result


#########################
# Cleanuper

class CleanupSquashRule(NamedTuple):
    """!!!

    A -> [...., B, ....]
    B -> [C]

    A -> [...., X, ....]  - X will have value of C, and name B or C.

    """
    parent_symbol: str
    cur_symbol: str
    child_symbol: str
    keep_current: bool


class StdCleanuper:
    """!!!"""

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

#    @classmethod
#    def make(cls, llparser: LLParser, keep_symbols) -> Self:
#
#        if keep_symbols is None:
#            keep_symbols = set()
#        keep_symbols.add(llparser.start_symbol_name)
#
#        list_item_symbols = set()
#        map_item_symbols = set()
#
#        container_item_symbols = list_item_symbols | map_item_symbols
#
#        # prepare squash rules
#        squash_rules_list = []
#        squash_symbols, choice_symbols = cls._make_squash_data(llparser)
#
#        for parent_symbol, rules_list in llparser.prods_map.items():
#            for prod_rule in rules_list:
#                for cur_symbol in prod_rule.production:
#                    if cur_symbol not in squash_symbols:
#                        continue
#
#                    must_keep_current = (
#                        prod_rule.symbol in choice_symbols
#                        or cur_symbol in keep_symbols)
#
#                    for rule in llparser.prods_map.get(cur_symbol):
#                        if not(rule.production):
#                            continue
#                        assert len(rule.production) == 1
#                        child_symbol = rule.production[0]
#
#                        must_keep_child = child_symbol in keep_symbols
#
#                        if must_keep_child and must_keep_current:
#                            continue
#
#                        if must_keep_child:
#                            keep_current = False
#                        else:
#                            keep_current = (
#                                must_keep_current
#                                or cur_symbol not in container_item_symbols)
#
#                        squash_rules_list.append(
#                            CleanupSquashRule(
#                                parent_symbol, cur_symbol,
#                                child_symbol, keep_current))
#
#        cleanuper = StdCleanuper(squash_rules_list, llparser.prod_templates)
#        cleanuper.keep_symbols = keep_symbols
#        return cleanuper

    def gen_detailed_descr(self):
        yield f"  keep_symbols: {sorted(self.keep_symbols)}"
        yield f"  choice_symbols: {sorted(self.choice_symbols)}"
        yield f"  squash_symbols: {sorted(self.squash_symbols)}"
        #yield f"  prod_templates: {sorted(self.prod_templates)}"


#    def gen_detailed_descr(self):
#        for (parent_symbol, cur_symbol), ch_map in sorted(self.squash_rules.items()):
#            for child_symbol, keep_current in sorted(ch_map.items()):
#                result_symbol = cur_symbol if keep_current else child_symbol
#                yield (
#                    f"    '{parent_symbol:8}' -> "
#                    f"[..., '{cur_symbol}' -> '{child_symbol}', ...] => "
#                    f"[..., '{result_symbol}', ...]")
#        yield "  Keep symbols:"
#        yield f"    {self.keep_symbols}"

    def cleanup(self, t_elem: TElement) -> None:
        """!!! """
        self._cleanup(t_elem)

    def _cleanup(
            self, t_elem: TElement,
            for_container: bool = False, for_choice: bool = False,
        ) -> bool:
        # !!!!
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
                assert False, "!!!! how can it happen?"
                continue
            child_no_squash = self._cleanup(
                child_elem,
                for_choice = t_elem.name in self.choice_symbols,
            )

            if child_elem.value is not None or child_elem.name in self.keep_symbols:
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

#    def cleanup(self, t_elem: TElement) -> TElement:
#        """Returns transformed copy of TElement."""
#        return self._transform_element('$START$', t_elem)
#
#    def _transform_element(self, parent_name, t_elem: TElement) -> TElement:
#
#        if t_elem.is_leaf():
#            return t_elem
#
#        if t_elem.name in self.prod_templates:
#            return self.prod_templates[t_elem.name].transform_t_elem(t_elem, self)
#
#        new_value = [
#            self._transform_element(t_elem.name, child_elem)
#            for child_elem in t_elem.value]
#
#        cur_squash_rules = self.squash_rules.get((parent_name, t_elem.name))
#
#        new_t_elem_value = new_value
#        if cur_squash_rules is not None and len(new_value) == 1:
#            # check if it's necessary to squash some tree element
#            # it's important that we name of the use not yet transformed value
#            # (new_value[0].name can be different)
#            keep_current = cur_squash_rules.get(t_elem.value[0].name)
#            if keep_current is not None:
#
#                if not keep_current:
#                    print(f"..... {t_elem.signature()=} -> {new_value[0]=}")
#                    return new_value[0]
#                else:
#                    # tmp workaround for current design of rules being poor :(
#                    must_keep_child = new_value[0].name in self.keep_symbols
#                    if not must_keep_child:
#                        new_t_elem_value = new_value[0].value
#
#                    #if t_elem.name in self.keep_symbols:
#                    #    # need to use self.keep_symbols to decide if
#                    #    # to keep child t_elem. Which is bad, because it was
#                    #    # supposed that using rules will be enough.
#                    #    print(f".. {must_keep_child=}")
#                    #    # else do no squashing
#
#        x = TElement(t_elem.name, new_t_elem_value, src_pos=t_elem.src_pos)
#        print(f"..... {t_elem.signature()=} -> {x.signature()=}")
#        return TElement(t_elem.name, new_t_elem_value, src_pos=t_elem.src_pos)

#    def reduce_list(self, t_elem: TElement) -> TElement:
#        """!!!"""
#        rules = self.lists_rules[t_elem.name]
#
#        if t_elem.value is None:
#            if rules.open_br is None:
#                # looks like in most cases if the list has no explicit open/close
#                # brackets then "no values" is an empty list, not None.
#                new_value = []
#            else:
#                new_value = None
#            return TElement(
#                t_elem.name, new_value, src_pos=t_elem.src_pos, is_leaf=True)
#
#        assert isinstance(t_elem.value, (list, tuple))
#
#        if rules.open_br is not None:
#            assert t_elem.value[0].name == rules.open_br, (
#                f"{t_elem=}, {rules.open_br=}")
#            assert t_elem.value[-1].name == rules.close_br
#            list_contents = t_elem.value[1:-1]
#        else:
#            list_contents = t_elem.value
#
#        new_values = []
#
#        # depending on grammar the first element may look
#        # like (item, opt_list) or like (opt_list)
#        assert len(list_contents) <= 2, f"{t_elem}"
#        if len(list_contents) == 2:
#            list_element = list_contents[0]
#            if list_element.value is not None:
#                # None value here means that this list_element corresponds to
#                # null production - that is there is no list element.
#
#                list_element = self._transform_element(
#                    list_element) # _for_container=True !!!!!!
#
#                new_values.append(list_element)
#            assert list_contents[1].name == rules.tail_symbol, (
#                f"expected {rules.tail_symbol}; got:\n{list_contents[0]}")
#            tail_value = list_contents[1]
#        else:
#            assert list_contents[0].name == rules.tail_symbol, (
#                f"expected {rules.tail_symbol}; got:\n{list_contents[0]}")
#            tail_value = list_contents[0]
#
#        tail_elems = self._reduce_list_tail(
#            tail_value, rules.delimiter, rules.tail_symbol)
#        tail_elems.reverse()
#
#        if tail_elems and tail_elems[-1] is None and rules.delimiter is not None:
#            # this element corresponds to the empty space after the last delimiter
#            tail_elems.pop()
#
#        new_values.extend(tail_elems)
#
#        return TElement(
#            t_elem.name, new_values, src_pos=t_elem.src_pos, is_leaf=True)
#
#    def _reduce_list_tail(self, t_elem, delimiter, tail_symbol):
#        # TElement corresponding to list tail -> [TElement, ] of list values
#        #          simple values also possible    ????????
#        assert t_elem.name == tail_symbol, (
#            f"{t_elem.name=}, {tail_symbol=} {delimiter=}, {t_elem=}")
#
#        if t_elem.value is None:
#            return []
#
#        assert isinstance(t_elem.value, (list, tuple))
#        # depending on grammar implementaion, whether this is the last
#        # element or not and other factors current element may look differently
#
#        assert len(t_elem.value) <= 3, f"{t_elem.value=}"
#        prod_values = [
#            e for e in t_elem.value if e.name is not None and e.name != delimiter]
#        if len(prod_values) == 2:
#            if prod_values[0].name == tail_symbol:
#                tail_elem = prod_values[0]
#                item_elem = prod_values[1]
#                assert item_elem.name != tail_symbol, f"{t_elem.value=}"
#            else:
#                assert prod_values[1].name == tail_symbol, f"{t_elem.value=}"
#                tail_elem = prod_values[1]
#                item_elem = prod_values[0]
#                assert item_elem.name != tail_symbol, f"{t_elem.value=}"
#        elif len(prod_values) == 1:
#            item_elem = prod_values[0]
#            tail_elem = None
#        elif len(prod_values) == 0:
#            item_elem = None
#            tail_elem = None
#        else:
#            assert False, f"{t_elem.value=}"
#
#        if tail_elem is not None:
#            assert item_elem is not None, f"{t_elem.signature()=}"
#            list_values = self._reduce_tail_list(tail_elem, delimiter, tail_symbol)
#        else:
#            list_values = []
#
#        if item_elem is not None:
#            item_elem = self._transform_element(item_elem) # !!! _for_container=True
#            if item_elem.value is None:
#                list_values.append(None)
#            else:
#                list_values.append(item_elem)
#
#        return list_values

#    def reduce_map(self, t_elem: TElement) -> TElement:
#        """Transform TElement subtree into {name: TElement}"""
#        rules = self.maps_rules[t_elem.name]
#
#        assert isinstance(t_elem.value, (list, tuple))
#
#        assert len(self.value) == 3, f"{t_elem}"
#        assert self.value[0].name == rules.open_br
#        assert self.value[1].name == rules.map_elements_name
#        assert self.value[2].name == rules.close_br
#
#        the_map = {}
#        self._reduce_elements_map_tail(t_elem.value[1], the_map, rules)
#
#        return TElement(t_elem.name, the_map, src_pos=t_elem.src_pos, is_leaf=True)
#
#    def _reduce_elements_map_tail(self, t_elem: TElement, the_map, rules) -> None:
#        # !!!!!!
#
#        assert t_elem.name == rules.map_elements_name
#
#        if t_elem.value is None or len(t_elem.value) == 0:
#            return
#
##        if t_elem.value[-1].name != map_elements_name:
##            assert False # find out how it can happen ??????
##            the_map = {}
##        else:
##            the_map = self._reduce_elements_map_tail(t_elem.value[-1], rules)
#
#        child_elements = []
#        for e in t_elem.value:
#            if e.name == rules.map_element_name:
#                child_elements.append(e)
#            elif e.name == rules.items_delimiter:
#                continue
#            elif e.name == rules.map_elements_name:
#                self._reduce_elements_map_tail(e, the_map, rules)
#            elif e.name is None:
#                # t_elem is a map tail, but it contains no elements
#                # (there is a ',' after last element)
#                assert len(t_elem.value) == 1
#                break
#            else:
#                assert False, f"unexpected element {e}"
#
#        assert len(child_elements) <= 1   # new, not sure. Comment required
#        
#        for item_element in child_elements:
#            assert len(item_element.value) == 3  # ?????  comment required
#            assert item_element.value[1].name == delimiter
#            key_elem = item_element.value[0]
#            if key_elem.is_leaf() and (
#                key_elem.value is None or isinstance(key_elem.value, str)
#            ):
#                key = key_elem.value
#            else:
#                key = key_elem
#            value_element = item_element.value[2]
#            self._transform_element(value_element)  # ?????  _for_container=True
#            if value_element.is_leaf():
#                the_map[key] = value_element.value
#            else:
#                the_map[key] = value_element



# 'THE_LIST': [
#     ('[', ']'),
#     ('[', 'ITEM', 'THE_LIST__TAIL', ']'),
# ],

# 'THE_LIST__TAIL': [
#     (',', 'ITEM', 'THE_LIST__TAIL'),
#     (',', ),     <- if last delimiter allowed
#     None,
# ],


# 'THE_LIST': [
#     ('[', 'THE_LIST__INNER', ']'),
# ]

# 'THE_LIST__INNER: [
#     None,
#     ('ITEM', ',', 'THE_LIST__INNER'),
#     ('ITEM', ),    - required only if separator is None
# ]







