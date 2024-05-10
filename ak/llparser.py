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
import itertools
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
            comments=None,
            synonyms=None, keywords=None,
            space_tokens=None, end_token_name="$END$",
        ):
        """_Tokenizer constructor.

        Arguments:
        - end_token_name: name of special token which corresponds to no text
            and indicates end of the text.
        - Check LLParser class for description of other arguments.
        """
        self.matcher = re.compile(tokenizer_str, re.VERBOSE)
        self.synonyms = synonyms or {}
        self.keywords = keywords or {}
        self.space_tokens = space_tokens or {'SPACE', 'COMMENT'}
        self.end_token_name = end_token_name

        assert comments is None or isinstance(comments, (list, tuple)), (
            f"'comments' must be list or tuple of comments descriptions, "
            f"got: {comments}")
        comments = comments if comments is not None else []
        self.eol_comments = set()
        self.ml_comments = {}  # {start_comment_text: end_comment_text}
        for comment_data in comments:
            if isinstance(comment_data, str):
                # this is 'to-end-of-line' comment
                self.eol_comments.add(comment_data)
            elif isinstance(comment_data, (list, tuple)):
                assert len(comment_data) == 2, (
                    f"expected (start_comment_text, end_comment_text), "
                    f"got {comment_data}")
                self.ml_comments[comment_data[0]] = comment_data[1]
            else:
                assert False, f"invalid 'comments' item: {comment_data}"

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

        chunks = self._strip_comments(enumereted_lines, src_name)

        for chunk in chunks:
            col = 0
            while col < len(chunk.text):
                match = self.matcher.match(chunk.text, col)
                if match is None:
                    raise LexicalError(
                        SrcPos(src_name, chunk.line_id, col),
                        chunk.text)
                token_name = match.lastgroup
                value = match.group(token_name)
                token_name = self.synonyms.get(token_name, token_name)
                keyword_token = self.keywords.get((token_name, value))
                if keyword_token is not None:
                    # this token is not a word, but keyword
                    token_name = keyword_token
                if token_name not in self.space_tokens:
                    yield _Token(
                        token_name,
                        SrcPos(src_name, chunk.line_id, chunk.start_pos + col + 1),
                        value)
                col = match.end()
        yield _Token(
            self.end_token_name, None, None)

    def _strip_comments(self, enumereted_lines, src_name):
        # remove comments from source text, yield _Tokenizer._Chunk

        cur_ml_comment_end = None
        cur_ml_comment_start_pos = None
        cur_ml_start_line_text = None
        for line_id, text in enumereted_lines:
            cur_pos = 0
            while cur_pos < len(text):
                if cur_ml_comment_end is not None:
                    end_pos = text.find(cur_ml_comment_end, cur_pos)
                    if end_pos == -1:
                        # the comment continues till end of line
                        cur_pos = len(text)
                        continue
                    cur_pos = end_pos + len(cur_ml_comment_end)
                    cur_ml_comment_end = None
                    cur_ml_comment_start_pos = None
                    cur_ml_start_line_text = None
                    continue
                # we are not inside a comment. Find comment start
                comments_pos = {}
                for start_comment_text, end_comment_text in self.ml_comments.items():
                    start = text.find(start_comment_text, cur_pos)
                    if start != -1:
                        comments_pos[start] = (start_comment_text, end_comment_text)
                for start_comment_text in self.eol_comments:
                    start = text.find(start_comment_text, cur_pos)
                    if start != -1:
                        comments_pos[start] = (start_comment_text, None)
                if comments_pos:
                    comment_start = min(comments_pos.keys())
                    start_comment_text, end_comment_text = comments_pos[comment_start]
                    if comment_start > cur_pos:
                        # report chunk of uncommented text
                        yield _Tokenizer._Chunk(
                            line_id, cur_pos, text[cur_pos:comment_start], text)
                    if end_comment_text is None:
                        # comment continues till end of line
                        cur_pos = len(text)
                        break
                    # comment continues till end_comment_text
                    cur_pos = comment_start + len(start_comment_text)
                    cur_ml_comment_end = end_comment_text
                    cur_ml_comment_start_pos = (line_id, comment_start)
                    cur_ml_start_line_text = text
                else:
                    # comments were not detected
                    if cur_pos == 0:
                        yield _Tokenizer._Chunk(line_id, 0, text, text)
                    else:
                        yield _Tokenizer._Chunk(
                            line_id, cur_pos, text[cur_pos:], text)
                    cur_pos = len(text)
        if cur_ml_comment_end is not None:
            raise LexicalError(
                SrcPos(
                    src_name,
                    cur_ml_comment_start_pos[0],
                    cur_ml_comment_start_pos[1],
                ),
                cur_ml_start_line_text,
                "comment is never closed")


class TElementCleanupRules:
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
                    f"(open_token, delimiter, tail_symbol, close_token)")
            open_token, delimiter, tail_symbol, close_token = properties
            _verify_is_non_terminal(list_symbol, "list symbol")
            _verify_is_non_terminal(tail_symbol, "list tail symbol")
            _verify_is_terminal(delimiter, True, "list delimiter symbol")
            if open_token is not None:
                if close_token is None:
                    raise GrammarError(
                        f"list open symbol '{open_token}' is not None, "
                        f"but close symbol is None")
            else:
                if close_token is not None:
                    raise GrammarError(
                        f"list open symbol is None, "
                        f"but close symbol '{close_token}' is not None")
            _verify_is_terminal(open_token, "list open symbol")
            _verify_is_terminal(close_token, "list close symbol")

        for map_symbol, properties in self.maps.items():
            if len(properties) != 6:
                raise GrammarError(
                    f"invalid cleanup rules for map symbol "
                    f"'{map_symbol}': {properties}. \n"
                    f"Expected tuple: "
                    f"(open_token, map_elements_name, items_delimiter, "
                    f"map_element_name, delimiter, close_token)"
                )
            (
                open_token,
                map_elements_name,
                items_delimiter,
                map_element_name,
                delimiter,
                close_token
            ) = properties
            _verify_is_non_terminal(map_elements_name, "map symbol")
            _verify_is_non_terminal(map_element_name, "map element symbol")
            _verify_is_terminal(open_token, "map open symbol")
            _verify_is_terminal(close_token, "map close symbol")
            _verify_is_terminal(items_delimiter, "map items_delimiter symbol")
            _verify_is_terminal(delimiter, "map delimiter symbol")
            if open_token is not None:
                if close_token is None:
                    raise GrammarError(
                        f"map open symbol '{open_token}' is not None, "
                        f"but close symbol is None")
            else:
                if close_token is not None:
                    raise GrammarError(
                        f"map open symbol is None, "
                        f"but close symbol '{close_token}' is not None")


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

    def signature(self):
        """Return tuple of symbols names.

        First element is self.name, names of child elements follow.
        """
        signature = [self.name]
        if not self.is_leaf():
            signature.extend(
                x.name if x is not None else None
                for x in self.value
            )
        return tuple(signature)

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

    def cleanup(
        self, rules=None, *,
        keep_symbols=None, lists=None, maps=None,
        _for_container=False,
        _for_choice=False,
    ):
        """Cleanup parsed tree.

        Syntax tree prepared by parser usually contains lots of nodes
        which keep little useful information (such as empty productions).
        This method cleans up the tree. It may be more convenient to get
        usefull info from it after cleanup.
        """
        if rules is not None:
            assert keep_symbols is None
            assert lists is None
            assert maps is None
        else:
            rules = TElementCleanupRules(
                keep_symbols=keep_symbols,
                lists=lists,
                maps=maps,
            )
        self._cleanup(rules, _for_container=_for_container, _for_choice=_for_choice)

    def _cleanup(self, rules, _for_container=False, _for_choice=False) -> bool:
        # do all the work of cleanup method
        #
        # returns 'elem_no_squash' - bool, which tells parent TElement if
        # this element can be squashed

        elem_no_squash = _for_choice

        if self.is_leaf():
            return elem_no_squash

        if self.name in rules.lists:
            self.reduce_list(rules, rules.lists[self.name])
            return elem_no_squash
        elif self.name in rules.maps:
            self.reduce_map(rules, rules.maps[self.name])
            return elem_no_squash

        values = []
        values_no_squash = []
        for child_elem in self.value:
            if child_elem is None:
                continue
            assert hasattr(child_elem, '_cleanup'), (
                f"{self=} {self._is_leaf=} {self.value=}")
            child_no_squash = child_elem._cleanup(
                rules,
                _for_choice = self.name in rules.choice_symbols
            )
            if child_elem.value is not None or child_elem.name in rules.keep_symbols:
                values.append(child_elem)
                values_no_squash.append(child_no_squash)

        if not values:
            self.value = None
            return elem_no_squash

        self.value = values

        if_squash = self.name in rules.squash_symbols

        if if_squash:
            assert isinstance(self.value, list)
            assert len(self.value) == 1, f"{self.name=} {self.value=}"
            assert len(self.value) == len(values_no_squash)
            child_elem = self.value[0]
            child_no_squash = values_no_squash[0]
            assert isinstance(child_elem, TElement)

            keep_parent = _for_choice or self.name in rules.keep_symbols
            keep_child = child_no_squash or child_elem.name in rules.keep_symbols

            if keep_parent and keep_child:
                if_squash = False
                elem_no_squash = True
            else:
                squash_parent = keep_child or _for_container

        if if_squash:
            if squash_parent:
                elem_no_squash = child_no_squash
                self.name = child_elem.name
                self.value = child_elem.value
                self._is_leaf = child_elem._is_leaf
            else:
                elem_no_squash = keep_parent
                self.value = child_elem.value
                self._is_leaf = child_elem._is_leaf

        return elem_no_squash

    def reduce_list(self, rules, list_properties):
        """Transform self.value subtree into a [TElement, ] of list values."""
        open_token, delimiter, tail_symbol, close_token = list_properties
        assert isinstance(self.value, (list, tuple))

        self._is_leaf = True

        if self.value is None:
            return

        if open_token is not None:
            assert self.value[0].name == open_token, f"{self=}, {open_token=}"
            assert self.value[-1].name == close_token
            self.value = self.value[1:-1]
        new_values = []

        # depending on grammar the first element may look
        # like (item, opt_list) or like (opt_list)
        assert len(self.value) <= 2, f"{self}"
        if len(self.value) == 2:
            list_element = self.value[0]
            if list_element.value is not None:
                # None value here means that this list_element corresponds to
                # null production - that is there is no list element.
                list_element._cleanup(rules, _for_container=True)
                new_values.append(list_element)
            assert self.value[1].name == tail_symbol, (
                f"expected {tail_symbol}; got:\n{self.value[0]}")
            tail_value = self.value[1]
        else:
            assert self.value[0].name == tail_symbol, (
                f"expected {tail_symbol}; got:\n{self.value[0]}")
            tail_value = self.value[0]

        next_elements = tail_value._reduce_tail_list(
            rules, delimiter, tail_symbol)
        next_elements.reverse()
        if next_elements and next_elements[-1] is None and delimiter is not None:
            # this element corresponds to the empty space after the last delimiter
            next_elements.pop()

        new_values.extend(next_elements)
        # new_values now contains TElement objects and Nones.
        # If some TElement is a leaf - replace it with it's value
        new_values = [
            x.value if isinstance(x, TElement) and x.is_leaf() else x
            for x in new_values
        ]
        self.value = new_values

    def _reduce_tail_list(self, rules, delimiter, tail_symbol):
        # TElement corresponding to list tail -> [TElement, ] of list values
        assert self.name == tail_symbol, (
            f"{self.name=}, {tail_symbol=} {delimiter=}, {self=}")

        if self.value is None:
            return []

        assert isinstance(self.value, (list, tuple))
        # depending on grammar implementaion, whether this is the last
        # element or not and other factors current element may look differently

        assert len(self.value) <= 3, f"{self.value=}"
        prod_values = [
            e for e in self.value if e.name is not None and e.name != delimiter]
        if len(prod_values) == 2:
            if prod_values[0].name == tail_symbol:
                tail_elem = prod_values[0]
                item_elem = prod_values[1]
                assert item_elem.name != tail_symbol, f"{self.value=}"
            else:
                assert prod_values[1].name == tail_symbol, f"{self.value=}"
                tail_elem = prod_values[1]
                item_elem = prod_values[0]
                assert item_elem.name != tail_symbol, f"{self.value=}"
        elif len(prod_values) == 1:
            item_elem = prod_values[0]
            tail_elem = None
        elif len(prod_values) == 0:
            item_elem = None
            tail_elem = None
        else:
            assert False, f"{self.value=}"

        if tail_elem is not None:
            assert item_elem is not None, f"{self.signature()=}"
            list_values = tail_elem._reduce_tail_list(
                rules, delimiter, tail_symbol)
        else:
            list_values = []

        if item_elem is not None:
            item_elem._cleanup(rules, _for_container=True)
            if item_elem.value is None:
                list_values.append(None)
            else:
                list_values.append(item_elem)

        return list_values

    def reduce_map(self, rules, map_properties):
        """Transform self.value subtree into {name: TElement}"""
        (
            open_token,
            map_elements_name,
            _items_delimiter,
            _map_element_name,
            _delimiter,
            close_token
        ) = map_properties
        assert isinstance(self.value, (list, tuple))

        self._is_leaf = True

        if self.value is None:
            return

        assert len(self.value) == 3, f"{self}"
        assert self.value[0].name == open_token
        assert self.value[1].name == map_elements_name
        assert self.value[2].name == close_token

        self.value = self.value[1]._reduce_elements_map_tail(
            rules, map_properties)

    def _reduce_elements_map_tail(self, rules, map_properties):
        (
            _open_token,
            map_elements_name,
            items_delimiter,
            map_element_name,
            delimiter,
            _close_token
        ) = map_properties

        assert self.name == map_elements_name

        if self.value is None or len(self.value) == 0:
            return {}

        if self.value[-1].name != map_elements_name:
            the_map = {}
        else:
            the_map = self.value[-1]._reduce_elements_map_tail(
                rules, map_properties)

        child_elements = []
        for e in self.value:
            if e.name == map_element_name:
                child_elements.append(e)
            elif e.name in (items_delimiter, map_elements_name):
                continue
            elif e.name is None:
                # self is a map tail, but it contains no elements
                # (there is a ',' after last element)
                assert len(self.value) == 1
                break
            else:
                assert False, f"unexpected element {e}"

        for item_element in child_elements:
            assert len(item_element.value) == 3
            assert item_element.value[1].name == delimiter
            key_elem = item_element.value[0]
            if key_elem.is_leaf() and (
                key_elem.value is None or isinstance(key_elem.value, str)
            ):
                key = key_elem.value
            else:
                key = key_elem
            value_element = item_element.value[2]
            value_element._cleanup(rules, _for_container=True)
            if value_element.is_leaf():
                the_map[key] = value_element.value
            else:
                the_map[key] = value_element

        return the_map


class ProdRule:
    """Info about prroduction rule 'A' -> ('B', 'C', 'D').

    Name 'production' is used for the result symbols, ('B', 'C', 'D') in this case.
    """
    __slots__ = 'symbol', 'production', 'sort_n', '_is_factorization_suffix'

    def __init__(self, symbol, production, sort_n):
        self.symbol = symbol
        self.production = production
        self.sort_n = sort_n
        self._is_factorization_suffix = False

    def __str__(self):
        return f"'{self.symbol}' -> {self.production}"


class ProdSequence:
    """Production which matches a sequence of elements.

    Can be considered as a short syntax for declaring of productions which
    implement parsing a list of elements. Several auxiliary symbols and
    productions will be created to implement parsing of sequences, but all
    these auxiliary symbols are stripped out from the final result. This happens
    unconditionally (unlike similar processing of actual list productions, which
    happens during optional cleanup procedure).
    """
    def __init__(self, *productions):
        self.productions = list(productions)


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
            self, terminals, parse_table,
            nullables, first_sest, follow_sets,
            cleanup_rules,
        ):
        self.terminals = terminals
        self.parse_table = parse_table
        self.nullables = nullables
        self.first_sest = first_sest
        self.follow_sets = follow_sets
        self.cleanup_rules = cleanup_rules

    def gen_detailed_descr(self):
        """Generate lines of human-readable description of the LLParser."""
        mk_descr_len = lambda x, size: f"'{x}'" + " "*(max(0, size - len(str(x))))

        yield "= Parser summary ="
        yield ""
        yield f"Terminals: {self.terminals}"
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
        yield ""
        yield "FirstSets:"
        for symbol, firsts in sorted(self.first_sest.items()):
            yield f"    {mk_descr_len(symbol, 10)}: {sorted(firsts)}"
        yield ""
        yield "FollowSets:"
        for symbol, follows in sorted(self.follow_sets.items()):
            yield f"    {mk_descr_len(symbol, 10)}: {sorted(follows)}"
        yield "Cleanup Rules:"
        yield from self.cleanup_rules.gen_detailed_descr()


class LLParser:
    """LLParser. Mostly LL1, but can deal with ambiguities in LL1 parsing table."""

    _END_TOKEN_NAME = '$END$'
    _INIT_PRODUCTION_NAME = '$START$'

    ProdSequence = ProdSequence
    AnyTokenExcept = AnyTokenExcept

    def __init__(
            self,
            tokenizer_str,
            *,
            productions,
            comments=None,
            synonyms=None,
            keywords=None,
            space_tokens=None,
            start_symbol_name='E',
            keep_symbols=None,
            lists=None,
            maps=None,
        ):
        """Constructor of LLParser.

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
        - space_tokens: set of names of tokens which should be skipped - usually
            tokens corresponding to empty spaces.
        - start_symbol_name: name of the symbol
        - comments: optional list of comments indicators. Each item of the list
            can be either str or (str, str). Examples:
            - '//'  - indicates comment to end of line
            - ('/*', '*/')  - specifies start and end of comment section
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
            comments=comments,
            synonyms=synonyms, keywords=keywords, space_tokens=space_tokens)

        self.terminals = self.tokenizer.get_all_token_names()

        self.start_symbol_name = start_symbol_name
        self.prods_map, self._seq_symbols = self._create_productions(
            productions, self.terminals)
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

        squash_symbols, choice_symbols = self._make_squash_data(keep_symbols)

        self.cleanup_rules = TElementCleanupRules(
            keep_symbols=keep_symbols,
            squash_symbols=squash_symbols, choice_symbols=choice_symbols,
            lists=lists,
            maps=maps,
        )
        self.cleanup_rules.verify_integrity(
            self.terminals,
            set(self.prods_map.keys()))

        self.parse_table, first_sets, follow_sets = self._make_llone_table(
            self.prods_map, self.terminals, nullables,
            self.start_symbol_name,
        )

        # used only for printing detailed description of the parser
        self._summary = ParserSummary(
            self.terminals,
            self.parse_table,
            nullables,
            first_sets,
            follow_sets,
            self.cleanup_rules,
        )

        self._verify_grammar_structure_part2(nullables)

    def parse(self, text, *, src_name="input text", debug=False, do_cleanup=True):
        """Parse the text."""
        tokens = list(self.tokenizer.tokenize(text, src_name))

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
                if cur_prod._is_factorization_suffix:
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
                        self.cleanup(root)
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

    def cleanup(self, t_element) -> None:
        """Clean up the tree with root in t_element.

        Usually the cleanup is performed in parse method, in this case there is
        no need to repeat the cleanup. Use this method only if parse was called
        with do_cleanup=False.
        """
        t_element.cleanup(
            self.cleanup_rules,
            _for_choice=True,  # keep root element during cleanup
        )

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
    def _create_productions(cls, prods_init_data, terminals, do_factorization=True):
        # constructor helper.
        # create ProdRule objects from productions data specified in constructor

        _sort_n_gen = itertools.count()

        prods_map = {}  # {symbol: [ProdRule, ]}
        seq_symbols = set()

        for symbol, productions in prods_init_data.items():
            assert '__' not in symbol, (
                f"Invalid production symbol '{symbol}'. Symbol names containing "
                f"'__' are reserved")

            is_seq_symbol = isinstance(productions, ProdSequence)

            # validate list of symbols specified in production
            prods_list = productions.productions if is_seq_symbol else productions
            for prod in prods_list:
                assert not isinstance(prod, str), (
                    f"invalid production {symbol} -> '{prod}'. "
                    f"(result should be tuple, not string)")

            if is_seq_symbol:
                seq_item_name = f"{symbol}__ITEM"
                prods_map[symbol] = [
                    ProdRule(symbol, (seq_item_name, symbol), next(_sort_n_gen)),
                    ProdRule(symbol, (), next(_sort_n_gen)),
                ]
                prods_map[seq_item_name] = cls._make_prod_rules_list(
                    seq_item_name, prods_list, terminals, _sort_n_gen)
                seq_symbols.add(symbol)
            else:
                prods_map[symbol] = cls._make_prod_rules_list(
                    symbol, prods_list, terminals, _sort_n_gen)

        if do_factorization:
            prods_map = cls._factorize_productions(prods_map)

        return prods_map, seq_symbols

    @classmethod
    def _factorize_productions(cls, prods_map):
        result_rules = {}

        for symbol, prod_rules in prods_map.items():
            for s, rr in cls._factorize_prods_list(symbol, prod_rules):
                assert s not in result_rules
                result_rules[s] = rr

        return result_rules

    @classmethod
    def _factorize_prods_list(cls, symbol, prod_rules):
        # factorize (combine productions with common prefix) all the productions
        # of a given symbol
        #
        # yield (symbol, [ProdRule, ]) for original symbol and all 'auxiliary'
        # symbols created during factorization process

        result_rules_list = []  # [ProdRule, ]

        _grp_id_gen = itertools.count()

        for chunk in cls._split_prods_rules(prod_rules):
            # chunk is a list of ProdRule with common prefix
            if len(chunk) == 1:
                result_rules_list.append(chunk[0])
            else:
                assert len(chunk) > 0
                group_production, extra_prods = cls._factorize_common_prefix_prods(
                    symbol, next(_grp_id_gen), chunk)
                for s, rr in extra_prods.items():
                    yield s, rr
                result_rules_list.append(group_production)

        yield symbol, result_rules_list

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
    def _factorize_common_prefix_prods(cls, symbol, group_id, prods_chunk):
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
        group_prod_rule._is_factorization_suffix = True

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

        aux_symbols_prod_rules = dict(  # {symbol: [ProdRule, ]}
            cls._factorize_prods_list(grp_symbol_suffix, suffix_prod_rules)
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

    def _make_squash_data(self, keep_symbols):
        # prepare information about potentially squashable symbols
        # (part of clenup procedure)

        keep_symbols = set() if keep_symbols is None else keep_symbols

        squash_symbols = set()
        choice_symbols = set()

        for symbol, prod_rules in self.prods_map.items():
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
