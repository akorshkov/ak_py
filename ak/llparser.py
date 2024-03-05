"""LL1 parser"""

import re
from collections import defaultdict
import collections.abc
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
            f"{descr} ({line}, {col}):\n{text}\n" +
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
            for i, s in enumerate(prod)) + "]"


class ParsingError(Error):
    """Unexpected token kind of errors."""
    def __init__(self, symbol, next_tokens, attempted_prods):
        self.src_pos = next_tokens[0].src_pos
        msg = (
            f"fail at {next_tokens}.\n"
            f"tried productions '{symbol}' -> {attempted_prods}")
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
            keep_symbols=None, reducing_symbols=None, lists=None, maps=None
        ):
        self.keep_symbols = set() if keep_symbols is None else keep_symbols
        self.reducing_symbols = {} if reducing_symbols is None else reducing_symbols
        self.lists = lists if lists is not None else {}
        self.maps = maps if maps is not None else {}

    def verify_integrity(self, terminals, non_terminals):
        """Verify correctness of rules."""

        for s in self.keep_symbols:
            if s not in terminals and s not in non_terminals:
                raise GrammarError(
                    f"unknown symbol '{s}' specified in {self.keep_symbols=}")

        for s in self.reducing_symbols.keys():
            if s not in terminals and s not in non_terminals:
                raise GrammarError(
                    f"unknown symbol '{s}' specified in {self.reducing_symbols=}")

        def _verify_is_terminal(symbol, descr="symbol"):
            if symbol in terminals:
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
            _verify_is_terminal(delimiter, "list delimiter symbol")
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

    def gen_descr(self, offset=0, print_name=True):
        """Generate lines of self description"""
        if not self.is_leaf():
            if print_name:
                yield "  " * offset + f"{self.name}:"
            for child in self.value:
                if child is None:
                    # this should be possible only in case self is a list,
                    # parsing results are cleaned-up, and the list contains
                    # None values.
                    yield "  " * (offset+1) + "None"
                else:
                    assert isinstance(child, TElement), f"{child=}"
                    yield from child.gen_descr(offset+1)
        elif isinstance(self.value, list):
            if len(self.value) == 0:
                yield "  " * offset + f"{self.name}: []"
            else:
                yield "  " * offset + f"{self.name}: ["
                for x in self.value:
                    if isinstance(x, TElement):
                        yield from x.gen_descr(offset+1)
                    else:
                        yield "  " * (offset + 1) + str(x)
                yield "  " * offset + "]"
        elif isinstance(self.value, dict):
            if print_name:
                yield "  " * offset + f"{self.name}:"
            for map_key, map_value in self.value.items():
                assert isinstance(map_value, TElement), f"{map_value=}"
                if map_value.is_leaf() and not isinstance(map_value.value, dict):
                    # make a single-line description: key: elem_name: value
                    elem_descr = "".join(map_value.gen_descr())
                    yield "  " * (offset+1) + f"{map_key}: {elem_descr}"
                    continue
                yield "  " * (offset+1) + f"{map_key}: {map_value.name}:"
                yield from map_value.gen_descr(offset+1, print_name=False)
        else:
            yield "  " * offset + f"{self.name}: {self.value}"

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
        keep_symbols=None, reducing_symbols=None, lists=None, maps=None,
    ):
        """Cleanup parsed tree.

        Syntax tree prepared by parser usually contains lots of nodes
        which keep little useful information (such as empty productions).
        This method cleans up the tree. It may be more convenient to get
        usefull info from it after cleanup.
        """
        if rules is not None:
            assert keep_symbols is None
            assert reducing_symbols is None
            assert lists is None
            assert maps is None
        else:
            rules = TElementCleanupRules(
                keep_symbols=keep_symbols,
                reducing_symbols=reducing_symbols,
                lists=lists,
                maps=maps)
        self._cleanup(rules)

    def _cleanup(self, rules):
        # do all the work of cleanup method

        if self.is_leaf():
            return

        if self.name in rules.lists:
            self.reduce_list(rules, rules.lists[self.name])
            return
        elif self.name in rules.maps:
            self.reduce_map(rules, rules.maps[self.name])
            return

        values = []
        for child_elem in self.value:
            if child_elem is None:
                continue
            if not hasattr(child_elem, 'cleanup'):
                print(f"{self}")
                print(f"{self._is_leaf=}")
                print(self.value)
            child_elem.cleanup(rules)
            if child_elem.value is not None or child_elem.name in rules.keep_symbols:
                values.append(child_elem)

        if not values:
            self.value = None
            return

        self.value = values
        reduce_up = rules.reducing_symbols.get(self.name)
        if reduce_up is not None and self.value is not None:
            assert isinstance(self.value, list)
            assert len(self.value) == 1
            child_elem = self.value[0]
            if reduce_up and child_elem.name not in rules.keep_symbols:
                self.value = child_elem.value
                self._is_leaf = child_elem._is_leaf
            elif not reduce_up and self.name not in rules.keep_symbols:
                self.name = child_elem.name
                self.value = child_elem.value
                self._is_leaf = child_elem._is_leaf

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
                list_element.cleanup(rules)
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
            item_elem.cleanup(rules)
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
            value_element.cleanup(rules)
            if value_element.is_leaf():
                the_map[key] = value_element.value
            else:
                the_map[key] = value_element

        return the_map


class _StackElement:
    # represents current position of parsing
    #
    # means: we try to match symbol starting from a token at given position
    # we have already matched first several symbols of current production
    # corresponding match results are stored in values
    def __init__(self, symbol, token_pos, prods):
        self.symbol = symbol
        self.start_token_pos = token_pos
        self.cur_token_pos = token_pos
        self.prods = prods
        self.cur_prod_id = 0
        self.values = []

    def clone(self):
        """clone self"""
        clone = _StackElement(self.symbol, self.start_token_pos, self.prods)
        clone.cur_token_pos = self.cur_token_pos
        clone.cur_prod_id = self.cur_prod_id
        clone.values = self.values[:]
        return clone

    def get_cur_prod(self):
        return self.prods[self.cur_prod_id]

    def get_cur_symbol(self):
        """Gen next unmatched symbol in current production."""
        return self.prods[self.cur_prod_id][len(self.values)]

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


class LLParser:
    """LLParser. Mostly LL1, but can deal with ambiguities in LL1 parsing table."""

    _END_TOKEN_NAME = '$END$'
    _INIT_PRODUCTION_NAME = '$START$'

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

        self.start_symbol_name = start_symbol_name
        self.productions = self._fix_empty_productions(productions)
        self.terminals = self.tokenizer.get_all_token_names()
        self.terminals.add(None)
        self.terminals.add(self._END_TOKEN_NAME)
        nullables = self._get_nullables(self.productions)

        self._verify_grammar_structure_part1()

        self.productions[self._INIT_PRODUCTION_NAME] = [
            (self.start_symbol_name, self._END_TOKEN_NAME)
        ]

        self.cleanup_rules = TElementCleanupRules(
            keep_symbols=keep_symbols,
            reducing_symbols=dict(
                self.make_reductable_symbols_map(self.productions)),
            lists=lists,
            maps=maps)
        self.cleanup_rules.verify_integrity(
            self.terminals,
            set(self.productions.keys()))

        self.parse_table, first_sets, follow_sets = self._make_llone_table(
            self.productions, self.terminals, nullables,
            self.start_symbol_name,
        )

        # used only for printing detailed description of the parser
        self._summary = (
            nullables,
            first_sets,
            follow_sets,
        )

        self._verify_grammar_structure_part2(nullables)

    def parse(self, text, *, src_name="input text", debug=False, do_cleanup=True):
        """Parse the text."""
        tokens = list(self.tokenizer.tokenize(text, src_name))

        parse_stack = [_StackElement(
            self._INIT_PRODUCTION_NAME, 0,
            self.productions[self._INIT_PRODUCTION_NAME])]
        longest_stack = []
        if debug:
            self._log_cur_prod(parse_stack, tokens)

        while True:
            top = parse_stack[-1]
            cur_prod = top.get_cur_prod()
            if len(top.values) == len(cur_prod):
                # production matched
                if debug:
                    self._log_match_result(parse_stack, tokens)
                new_elem_value = top.values
                if len(new_elem_value) == 1 and new_elem_value[0].name is None:
                    # this element corresponds to null production
                    new_elem_value = None
                value = TElement(top.symbol, new_elem_value)
                new_token_pos = top.cur_token_pos
                parse_stack.pop()
                if not parse_stack:
                    # success!
                    # value now is the TElement corresponding to technical
                    # initial production '$START$' -> ('E', '$END$').
                    assert len(value.value) == 2
                    root = value.value[0]
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
                top.next_matched(value, new_token_pos)
                continue
            next_token = tokens[top.cur_token_pos]
            cur_symbol = top.get_cur_symbol()

            if cur_symbol in self.terminals:
                # try to match current token with next symbol
                if cur_symbol is None:
                    top.next_matched(
                        None,
                        top.cur_token_pos)
                    continue
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
                    parse_stack.append(
                        _StackElement(cur_symbol, top.cur_token_pos, prods))
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
                if elem.cur_prod_id < len(elem.prods) - 1:
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
            attempted_prods = top.prods
            raise ParsingError(top.symbol, next_tokens, attempted_prods)

    def cleanup(self, t_element) -> None:
        """Clean up the tree with root in t_element.

        Usually the cleanup is performed in parse method, in this case there is
        no need to repeat the cleanup. Use this method only if parse was called
        with do_cleanup=False.
        """
        t_element.cleanup(self.cleanup_rules)

    def _verify_grammar_structure_part1(self):
        # initial verification of grammar structure
        # to be called before parse_table is prepared
        if self.start_symbol_name not in self.productions:
            raise GrammarError(
                f"no productions for start symbol '{self.start_symbol_name}'")

        if self._END_TOKEN_NAME in self.productions:
            raise GrammarError(
                f"production specified for end symbol '{self._END_TOKEN_NAME}'")

        if self._INIT_PRODUCTION_NAME in self.productions:
            raise GrammarError(
                f"production specified explicitely for "
                f"special symbol '{self._INIT_PRODUCTION_NAME}'")

        non_terminals = set(self.productions.keys())
        bad_tokens = non_terminals.intersection(self.terminals)

        if bad_tokens:
            raise GrammarError(
                f"Production(s) specified for terminal symbols {bad_tokens}")

        all_prod_symbols = {
            s
            for prods in self.productions.values()
            for prod in prods
            for s in prod}
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
        for symbol, prods in sorted(self.productions.items()):
            # depth-first-search of the same symbol
            if symbol in processed_symbols:
                continue
            # (symbol, prods, cur_prod_id, cur_symbol_id)
            stack = [[symbol, prods, 0, 0], ]
            def _next_prod(_stack):
                _stack[-1][2] += 1
                _stack[-1][3] = 0

            def _next_symbol(_stack):
                _stack[-1][3] += 1

            while stack:
                top = stack[-1]
                prod_symbol, prods, cur_prod_id, cur_symbol_id = top
                if cur_prod_id >= len(prods):
                    stack.pop()
                    processed_symbols.add(prod_symbol)
                    if stack:
                        top = stack[-1]
                        cur_prod = top[1][top[2]]
                        cur_prod_symbol = cur_prod[top[3]]
                        if cur_prod_symbol in nullables:
                            _next_symbol(stack)
                        else:
                            _next_prod(stack)
                    continue
                cur_prod = prods[cur_prod_id]
                if cur_symbol_id >= len(cur_prod):
                    _next_prod(stack)
                    continue
                cur_symbol = cur_prod[cur_symbol_id]
                # check if this symbol is already present on stack
                for i, (stack_symbol, _, _, _) in enumerate(stack):
                    if stack_symbol == cur_symbol:
                        # found cycle
                        cycle_data = [
                            (s, prods[prod_id], symbol_id)
                            for s, prods, prod_id, symbol_id in stack[i:]  # stack[i:]
                        ]
                        raise GrammarIsRecursive(cycle_data, nullables)

                if cur_symbol in processed_symbols:
                    _next_prod(stack)
                    continue
                # cur_symbol is non-terminal. May need to go deeper
                if cur_symbol_id > 0:
                    prev_symbol = cur_prod[cur_symbol_id-1]
                    prev_symbol_is_nullable = prev_symbol in nullables
                else:
                    prev_symbol_is_nullable = True

                if not prev_symbol_is_nullable:
                    # do not check current symbol because previous not nullable
                    _next_prod(stack)
                    continue

                # do need to go deeper
                stack.append([cur_symbol, self.productions[cur_symbol], 0, 0])

    def _log_cur_prod(self, parse_stack, tokens):
        # log current production
        top = parse_stack[-1]
        prefix = "  "*(len(parse_stack) - 1)
        if top.cur_prod_id == 0:
            self._log_debug(
                prefix + "try match '%s': (next token #%s) %s)",
                parse_stack[-1].symbol, top.start_token_pos,
                tokens[top.start_token_pos])
        self._log_debug(
            prefix + "- (%s/%s) %s",
            top.cur_prod_id+1, len(top.prods), top.get_cur_prod())

    def _log_match_result(self, parse_stack, tokens):
        # log result of the match
        prefix = "  "*(len(parse_stack) - 1)
        top = parse_stack[-1]
        cur_prod = top.get_cur_prod()
        is_success = len(top.values) == len(cur_prod)
        if is_success:
            self._log_debug(prefix + "'%s' matched", top.symbol)
        else:
            failed_symbol = cur_prod[len(top.values)]
            failed_token = tokens[top.cur_token_pos]
            self._log_debug(
                prefix + "'%s' desn't match. Prod symbol '%s' doesn't match '%s'",
                top.symbol,
                failed_symbol, failed_token)

    def _log_debug(self, *args, **kwargs):
        logger.error(*args, **kwargs)

    @classmethod
    def _make_llone_table(cls, productions, terminals, nullables, start_symbol_name):
        """Make Parsing Table.

        Returns possible productions for non-terminal-symbol and next token:
            {(non_term_symbol, next_token): [production, ]}
        """
        first_sets = cls._calc_first_sets(productions, terminals, nullables)
        follow_sets = cls._calc_follow_sets(
            productions, terminals, nullables, first_sets, start_symbol_name)

        parse_table = defaultdict(list)
        for non_term, prods in productions.items():
            for prod in prods:
                assert len(prod) > 0
                start_symbols = set()
                for symbol in prod:
                    if symbol is None:
                        assert len(prod) == 1
                        continue
                    if symbol in terminals:
                        start_symbols.add(symbol)
                        break
                    # symbol is non-terminal
                    start_symbols |= first_sets[symbol]
                    if symbol not in nullables:
                        break
                else:
                    # all the symbols in prod are nullable
                    assert non_term in nullables
                    start_symbols |= follow_sets[non_term]

                for first_symbol in start_symbols:
                    parse_table[(non_term, first_symbol)].append(prod)

        return parse_table, first_sets, follow_sets

    @classmethod
    def _calc_follow_sets(
        cls, productions, terminals, nullables, first_sets, start_symbol_name,
    ):
        """Calculate 'follow-sets'

        {'NON_TERM': set(t| S ->* b NON_TERM t XXX)}
        """
        assert start_symbol_name in productions, (
            f"invalid grammar: there are no productions for "
            f"start symbol '{start_symbol_name}'")

        follow_sets = {non_term: set() for non_term in productions.keys()}
        follow_sets[start_symbol_name].add(cls._END_TOKEN_NAME)

        # follows dependencies rules: follow set for a symbol must include
        # follow sets of all the dependent symbols
        follows_deps = {non_term: set() for non_term in productions.keys()}

        # 1. calculate 'immediate follows' - cases when non-terminal symbol
        # is followed by terminal or non-terminal in some production
        for non_term, prods in sorted(productions.items()):
            for prod in prods:
                for i, cur_symbol in enumerate(prod):
                    if cur_symbol in terminals:
                        continue
                    for next_symbol in prod[i+1:]:
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
    def _get_nullables(productions):
        # get set of all nullable symbols
        cur_set = set([None, ])
        next_set = set()
        while len(cur_set) != len(next_set):
            next_set.update(cur_set)
            for non_term, prods in productions.items():
                if non_term in next_set:
                    continue
                if any(all(s in cur_set for s in prod) for prod in prods):
                    next_set.add(non_term)
            cur_set, next_set = next_set, cur_set
        cur_set.remove(None)
        return cur_set

    def print_detailed_descr(self):
        """Print detailed description of the parser."""
        nullables, first_sest, follow_sets = self._summary

        mk_descr_len = lambda x, size: f"'{x}'" + " "*(max(0, size - len(str(x))))

        print("= Parser summary =")
        print("")
        print(f"Terminals: {self.terminals}")
        print("")
        print("Parse Table:")
        cur_symbol = None
        for (symbol, token), prods in self.parse_table.items():
            if symbol != cur_symbol:
                print(f"    '{symbol}':")
                cur_symbol = symbol
            token_descr = mk_descr_len(token, 10)
            for prod in prods:
                print(f"        {token_descr}->{prod}")
        print("")
        print(f"Nullables: {nullables}")
        print("")
        print("FirstSets:")
        for symbol, firsts in sorted(first_sest.items()):
            print(f"    {mk_descr_len(symbol, 10)}: {sorted(firsts)}")
        print("")
        print("FollowSets:")
        for symbol, follows in sorted(follow_sets.items()):
            print(f"    {mk_descr_len(symbol, 10)}: {sorted(follows)}")

    @classmethod
    def _calc_first_sets(cls, productions, terminals, nullables):
        # for each symbol get list of tokens it's production can start from
        #
        # {NON_TERM: {t| NON_TERM ->* tXXX}}
        non_terms = set(productions.keys())

        fsets = {t: set() for t in non_terms}

        while True:
            fsets_updated = False
            for non_term, cur_fset in fsets.items():
                for prod in productions[non_term]:
                    for symbol in prod:
                        if symbol in terminals:
                            if symbol is None:
                                continue
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

    @staticmethod
    def _fix_empty_productions(prods_map):
        """Replace production 'None' with (None, )"""
        for symbol, prods in prods_map.items():
            for prod in prods:
                assert not isinstance(prod, str), (
                    f"invalid production {symbol} -> '{prod}'. "
                    f"(result should be tuple, not string)")

        return {
            symbol: [(None, ) if prod is None else prod for prod in prods]
            for symbol, prods in prods_map.items()
        }

    @staticmethod
    def make_reductable_symbols_map(prods_map):
        """Make map of reducable symbols (for cleanup procedure).

        Returns {symbol: if_reduce_up}

        if_reduce_up = True - means the production for this symbol looks like
        'A': [('B', )] - that is 'A' is just alternative name of 'B'.
        Only name 'A' will remain in cleaned up tree.

        if_reduce_up = False - means the production for this symbol looks like
        'A': [
          ('B', ),
          ('C', ),
          ('D', ),
        ] - that is 'A' may be either 'B' or 'C' or 'D'.
        Name 'A' will be cleaned up from the tree.
        """
        for symbol, prods_list in prods_map.items():
            n_one_val_prods = sum(
                1 if prod is not None and len(prod) == 1 else 0
                for prod in prods_list)
            n_null_prods = sum(
                1 if prod is None or len(prod) == 0 else 0
                for prod in prods_list)

            if n_one_val_prods + n_null_prods < len(prods_list):
                # there are more complex prods, no reduction is possible
                continue

            if_up = n_one_val_prods == 1
            yield symbol, if_up
