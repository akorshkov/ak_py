"""LL1 parser"""

import re
from collections import defaultdict
import logging


logger = logging.getLogger(__name__)


class Error(Exception):
    """Common parsing error"""
    pass


class LexicalError(Error):
    """Error happened during lexical parsing"""
    def __init__(self, line, col, text):
        self.line = line
        self.col = col
        self.text = text
        super().__init__(
            f"unexpected symbol at ({line}, {col}):\n{text}\n" +
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
        # if len():
        msg = (
            f"fail at {next_tokens}.\n"
            f"tried productions '{symbol}' -> {attempted_prods}")
        super().__init__(msg)


class _Token:
    # information about a single token
    # (first phase of parsing is to split text into tokens)
    __slots__ = 'name', 'line', 'col', 'value'

    def __init__(self, name, line, col, value):
        self.name = name
        self.line = line
        self.col = col
        self.value = value

    def __str__(self):
        return f"{self.name}({self.line},{self.col}){{{self.value}}}"

    def __repr__(self):
        return str(self)


class _Tokenizer:
    # split line of text into tokens
    class _Chunk:
        # line of text to tokenize
        __slots__ = "line_number", "start_pos", "text", "orig_text"
        def __init__(self, line_number, start_pos, text, orig_text):
            self.line_number = line_number
            self.start_pos = start_pos
            self.text = text
            self.orig_text = text if orig_text is None else orig_text

    def __init__(
            self,
            tokenizer_str,
            *,
            synonyms=None, keywords=None,
            space_tokens=None, end_token_name="$END$",
        ):
        self.matcher = re.compile(tokenizer_str, re.VERBOSE)
        self.synonyms = synonyms or {}
        self.keywords = keywords or {}
        self.space_tokens = space_tokens or {'SPACE', 'COMMENT'}
        self.end_token_name = end_token_name

    def get_all_token_names(self):
        """Get names of all tokens this tokenizer knows about."""
        tokens = set(self.matcher.groupindex.keys())
        tokens -= self.synonyms.keys()
        tokens.update(self.synonyms.values())
        tokens.update(self.keywords.values())
        return tokens

    def tokenize(self, chunks):
        """chunks of text -> _Token objects"""
        if isinstance(chunks, str):
            chunks = [
                self._Chunk(i, 0, line.rstrip(), None)
                for i, line in enumerate(chunks.split('\n'))
            ]

        line, col = 0, 0
        for chunk in chunks:
            col = 0
            while col < len(chunk.text):
                match = self.matcher.match(chunk.text, col)
                if match is None:
                    raise LexicalError(line, col, chunk.text)
                token_name = match.lastgroup
                value = match.group(token_name)
                token_name = self.synonyms.get(token_name, token_name)
                keyword_token = self.keywords.get((token_name, value))
                if keyword_token is not None:
                    # this token is not a word, but keyword
                    token_name = keyword_token
                if token_name not in self.space_tokens:
                    yield _Token(token_name, line, chunk.start_pos + col, value)
                col = match.end()
        yield _Token(self.end_token_name, line, col, None)


class TElement:
    """Element of tree, which represents parsing results.

    value can be:
        - string - for terminal symbols
        - [TElement, ] - for non-terminal symbols
    """
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __str__(self):
        if not self.is_leaf():
            return f"TE<{self.name}>[" + ",".join(
                str(x) for x in self.value) + "]"
        else:
            return f"TE<{self.name}>/{self.value}/"

    def __repr__(self):
        return str(self)

    def is_leaf(self) -> bool:
        """Check if self is a tree leaf."""
        return not isinstance(self.value, list)

    def signature(self):
        """Return tuple of symbols names.

        First element is self.name, names of value names follows.
        """
        signature = [self.name]
        if not self.is_leaf():
            signature.extend(
                x.name if x is not None else None
                for x in self.value
            )
        return tuple(signature)

    def gen_descr(self, offset=0):
        """Generate lines of self description"""
        if isinstance(self.value, list):
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
        else:
            yield "  " * offset + f"{self.name}: {self.value}"

    def printme(self):
        """Pretty-print the tree with root in self"""
        for x in self.gen_descr():
            print(x)

    def cleanup(self, keep_symbols=None, lists=None):
        """Cleanup parsed tree.

        Syntax tree prepared by parser usually contains lots of nodes
        which keep little useful information (such as empty productions).
        This method cleans up the tree. It may be more convenient to get
        usefull info from it after cleanup.
        """
        keep_symbols = keep_symbols if keep_symbols is not None else set()
        lists = lists if lists is not None else {}
        keep_symbols.update(lists.keys())
        if self.value is None and self.name not in keep_symbols:
            return None
        if self.is_leaf():
            return self
        values = []
        if self.name in lists:
            self.reduce_list(keep_symbols, lists, lists[self.name])
            return self
        for value in self.value:
            if value is None:
                continue
            new_value = value.cleanup(keep_symbols, lists)
            if new_value is not None:
                values.append(new_value)
        if not values:
            return None
        self.value = values
        # reduce a chain of elements having a single value.
        # ('E', [('SLAG', [('SOME', ('WORD', "value"))]])
        # -> ('E', [('WORD', "value")])
        if len(values) == 1:
            if self.name in keep_symbols:
                if values[0].name not in keep_symbols:
                    self.value = values[0].value
            else:
                self.name = values[0].name
                self.value = values[0].value

        return self

    def reduce_list(self, keep_symbols, lists, list_properties):
        """Transform self.value subtree into a [TElement, ] of list values."""
        open_token, delimiter, tail_symbol, close_token = list_properties
        assert isinstance(self.value, (list, tuple))

        if self.value[0].name is None:
            return

        if open_token is not None:
            assert self.value[0].name == open_token, f"{self=}, {open_token=}"
            assert self.value[-1].name == close_token
            self.value = self.value[1:-1]
        new_values = []

        # depending on grammar the first element may look
        # like (item, opt_list) or like (opt_list)
        assert len(self.value) <= 2
        if len(self.value) == 2:
            new_values.append(self.value[0].cleanup(keep_symbols, lists))
            assert self.value[1].name == tail_symbol
            tail_value = self.value[1]
        else:
            assert self.value[0].name == tail_symbol
            tail_value = self.value[0]

        next_elements = tail_value._reduce_tail_list(
            keep_symbols, lists, delimiter, tail_symbol)
        next_elements.reverse()
        if next_elements and next_elements[-1] is None and delimiter is not None:
            # this element corresponds to the empty space after the last delimiter
            next_elements.pop()

        new_values.extend(next_elements)
        self.value = new_values

    def _reduce_tail_list(self, keep_symbols, lists, delimiter, tail_symbol):
        # TElement corresponding to list tail -> [TElement, ] of list values
        assert self.name == tail_symbol, (
            f"{self.name=}, {tail_symbol=} {delimiter=}, {self=}")
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
                keep_symbols, lists, delimiter, tail_symbol)
        else:
            list_values = []

        if item_elem is not None:
            list_values.append(item_elem.cleanup(keep_symbols, lists))

        return list_values


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
        assert isinstance(value, TElement)
        self.values.append(value)
        self.cur_token_pos = new_token_pos

    def switch_to_next_prod(self):
        self.values = []
        self.cur_token_pos = self.start_token_pos
        self.cur_prod_id += 1


class LLParser:
    """LLParser. Mostly LL1, but can deal with ambiguities in LL1 parsing table."""
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
            end_token_name="$END$",
            keep_symbols=None,
            lists=None,
        ):
        self.tokenizer = _Tokenizer(
            tokenizer_str,
            synonyms=synonyms, keywords=keywords, space_tokens=space_tokens)

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
                assert False

        self.start_symbol_name = start_symbol_name
        self.end_token_name = end_token_name
        self.keep_symbols = keep_symbols
        self.lists = lists
        self.init_production_name = '$START$'
        self.productions = self._fix_empty_productions(productions)

        self.terminals = self.tokenizer.get_all_token_names()
        self.terminals.add(None)
        self.terminals.add(self.end_token_name)
        nullables = self._get_nullables(self.productions)

        self._verify_grammar_structure_part1()

        self.productions[self.init_production_name] = [
            (self.start_symbol_name, self.end_token_name)
        ]

        self.parse_table, first_sets, follow_sets = self._make_llone_table(
            self.productions, start_symbol_name, end_token_name,
            self.terminals, nullables)

        # used only for printing detailed description of the parser
        self._summary = (
            nullables,
            first_sets,
            follow_sets,
        )

        self._verify_grammar_structure_part2(nullables)

    def parse(self, lines, *, debug=False, do_cleanup=True):
        """Parse the text."""
        tokens = list(
            self.tokenizer.tokenize(self._strip_comments(lines))
        )

        parse_stack = [_StackElement(
            self.init_production_name, 0,
            self.productions[self.init_production_name])]
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
                value = TElement(top.symbol, top.values)
                new_token_pos = top.cur_token_pos
                parse_stack.pop()
                if not parse_stack:
                    # success!
                    # value now is the TElement corresponding to technical
                    # initial production '$START$' -> ('E', '$END$').
                    assert len(value.value) == 2
                    root = value.value[0]
                    if debug:
                        print("ROW RESULT:")
                        root.printme()
                    if do_cleanup:
                        root.cleanup(self.keep_symbols, self.lists)
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
                        TElement(cur_symbol, None),
                        top.cur_token_pos)
                    continue
                if next_token.name == cur_symbol:
                    top.next_matched(
                        TElement(cur_symbol, next_token.value),
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

    def _strip_comments(self, lines):
        # remove comments from source text, yield _Tokenizer._Chunk
        if isinstance(lines, str):
            lines = [line.rstrip() for line in lines.split('\n')]

        for line_id, text in enumerate(lines):
            cur_pos = 0
            cur_ml_comment_end = None
            while cur_pos < len(text):
                if cur_ml_comment_end is not None:
                    end_pos = text.find(cur_ml_comment_end, cur_pos)
                    if end_pos == -1:
                        # the comment continues till end of line
                        cur_pos = len(text)
                        continue
                    cur_pos = end_pos + len(cur_ml_comment_end)
                    cur_ml_comment_end = None
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
                else:
                    # comments were not detected
                    if cur_pos == 0:
                        yield _Tokenizer._Chunk(line_id, 0, text, text)
                    else:
                        yield _Tokenizer._Chunk(
                            line_id, cur_pos, text[cur_pos:], text)
                    cur_pos = len(text)

    def _verify_grammar_structure_part1(self):
        # initial verification of grammar structure
        # to be called before parse_table is prepared
        if self.start_symbol_name not in self.productions:
            raise GrammarError(
                f"no productions for start symbol '{self.start_symbol_name}'")

        if self.end_token_name in self.productions:
            raise GrammarError(
                f"production specified for end symbol '{self.end_token_name}'")

        if self.init_production_name in self.productions:
            raise GrammarError(
                f"production specified explicitely for "
                f"special symbol '{self.init_production_name}'")

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

        if self.end_token_name in all_prod_symbols:
            raise GrammarError(
                f"special end token '{self.end_token_name}' is explicitely "
                f"used in productions")

        if self.init_production_name in all_prod_symbols:
            raise GrammarError(
                f"special start symbol '{self.init_production_name}' is explicitely "
                f"used in productions")

        if self.keep_symbols is not None:
            for s in self.keep_symbols:
                if s not in self.terminals and s not in non_terminals:
                    raise GrammarError(
                        f"unknown symbol '{s}' specified in {self.keep_symbols=}")

        def _verify_is_terminal(symbol, descr="symbol"):
            if symbol in self.terminals:
                return
            if symbol in non_terminals:
                raise GrammarError(f"{descr} '{symbol}' is non-terminal symbol")
            raise GrammarError(f"{descr} '{symbol}' is unknown")

        def _verify_is_non_terminal(symbol, descr="symbol"):
            if symbol in non_terminals:
                return
            if symbol in self.terminals:
                raise GrammarError(f"{descr} '{symbol}' is terminal")
            raise GrammarError(f"{descr} '{symbol}' is unknown")

        if self.lists is not None:
            for list_symbol, properties in self.lists.items():
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
    def _make_llone_table(
            cls, productions, start_symbol_name, end_token_name,
            terminals, nullables):
        """Make Parsing Table.

        Returns possible productions for non-terminal-symbol and next token:
            {(non_term_symbol, next_token): [production, ]}
        """
        first_sets = cls._calc_first_sets(productions, terminals, nullables)
        follow_sets = cls._calc_follow_sets(
            productions, terminals, nullables, first_sets,
            start_symbol_name, end_token_name)

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
        cls, productions, terminals, nullables, first_sets,
        start_symbol_name, end_token_name,
    ):
        """Calculate 'follow-sets'

        {'NON_TERM': set(t| S ->* b NON_TERM t XXX)}
        """
        assert start_symbol_name in productions, (
            f"invalid grammar: there are no productions for "
            f"start symbol '{start_symbol_name}'")

        follow_sets = {non_term: set() for non_term in productions.keys()}
        follow_sets[start_symbol_name].add(end_token_name)

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
