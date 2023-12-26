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
    def __init__(self, cycle_data):
        msg = "grammar is recursive:\n" + "\n".join(
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
        return {
            self.synonyms.get(s, s) for s in self.matcher.groupindex.keys()
        }

    def tokenize(self, lines):
        """lines of text -> _Token objects"""
        if isinstance(lines, str):
            lines = list(lines.split('\n'))

        line, col = 0, 0
        for line, text in enumerate(lines):
            col = 0
            while col < len(text):
                match = self.matcher.match(text, col)
                if match is None:
                    raise LexicalError(line, col, text)
                token_name = match.lastgroup
                value = match.group(token_name)
                token_name = self.synonyms.get(token_name, token_name)
                keyword_token = self.keywords.get((token_name, value))
                if keyword_token is not None:
                    # this token is not a word, but keyword
                    token_name = keyword_token
                if token_name not in self.space_tokens:
                    yield _Token(token_name, line, col, value)
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
        if self.is_leaf():
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
            signature.extend(x.name for x in self.value)
        return tuple(signature)

    def gen_descr(self, offset=0):
        if isinstance(self.value, list):
            yield "  " * offset + f"{self.name}:"
            for child in self.value:
                yield from child.gen_descr(offset+1)
        else:
            yield "  " * offset + f"{self.name}: {self.value}"

    def printme(self):
        """Pretty-print the tree with root in self"""
        for x in self.gen_descr():
            print(x)

    def cleanup(self, keep_symbols=None):
        """Cleanup parsed tree.

        Syntax tree prepared by parser usually contains lots of nodes
        which keep little useful information (such as empty productions).
        This method cleans up the tree. It may be more convenient to get
        usefull info from it after cleanup.
        """
        keep_symbols = keep_symbols or set()
        if self.value is None and self.name not in keep_symbols:
            return None
        if self.is_leaf():
            return self
        values = []
        for value in self.value:
            if value is None:
                continue
            new_value = value.cleanup()
            if new_value is not None:
                values.append(new_value)
        if not values:
            return None
        self.value = values
        # reduce a chain of elements having a single value.
        # ('E', [('SLAG', [('SOME', ('WORD', "value"))]])
        # -> ('E', [('WORD', "value")])
        if len(values) == 1:
            if not values[0].is_leaf() and not values[0].name in keep_symbols:
                values[0].name = self.name
            return values[0]

        return self


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
            synonyms=None,
            keywords=None,
            space_tokens=None,
            start_symbol_name='E',
            end_token_name="$END$",
            debug=False,
        ):
        self.tokenizer = _Tokenizer(
            tokenizer_str,
            synonyms=synonyms, keywords=keywords, space_tokens=space_tokens)
        self.start_symbol_name = start_symbol_name
        self.end_token_name = end_token_name
        self.init_production_name = '$START$'
        self._debug = debug
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

    def parse(self, lines):
        """Parse the text."""
        tokens = list(self.tokenizer.tokenize(lines))

        parse_stack = [_StackElement(
            self.init_production_name, 0,
            self.productions[self.init_production_name])]
        longest_stack = []
        self._log_cur_prod(parse_stack, tokens)

        while True:
            top = parse_stack[-1]
            cur_prod = top.get_cur_prod()
            # print(f"... trying {top.symbol} -> {cur_prod}; {top.values}")
            if len(top.values) == len(cur_prod):
                # production matched
                self._log_match_result(parse_stack, tokens)
                value = TElement(top.symbol, top.values)
                new_token_pos = top.cur_token_pos
                parse_stack.pop()
                if not parse_stack:
                    # success!
                    # value now is the TElement corresponding to technical
                    # initial production '$START$' -> ('E', '$END$').
                    assert len(value.value) == 2
                    return value.value[0]
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
                    self._log_cur_prod(parse_stack, tokens)
                    continue

            # current production does not match. Try to rollback
            # and attempt other options
            # Find rollback point
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
                self._log_cur_prod(parse_stack, tokens)
                continue

            # report fail. Looks like it's good idea to describe the path
            # which reached fartherst when trying to parse the text
            top = longest_stack[-1] if longest_stack else parse_stack[-1]
            next_tokens = tokens[top.start_token_pos:top.start_token_pos+5]
            attempted_prods = top.prods
            raise ParsingError(top.symbol, next_tokens, attempted_prods)

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
            stack = [[symbol, prods, 0, 0], ]  # (prods, cur_prod_id, cur_symbol_id)
            def _next_prod(_stack):
                _stack[-1][2] += 1
                _stack[-1][3] = 0

            while stack:
                top = stack[-1]
                prod_symbol, prods, cur_prod_id, cur_symbol_id = top
                if cur_prod_id >= len(prods):
                    stack.pop()
                    processed_symbols.add(prod_symbol)
                    if stack:
                        stack[-1][3] += 1
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
                            for s, prods, prod_id, symbol_id in stack[i:]
                        ]
                        raise GrammarIsRecursive(cycle_data)

                if cur_symbol in processed_symbols:
                    _next_prod(stack)
                    continue
                # cur_symbol is non-terminal. May need to go deeper
                if cur_symbol_id > 0:
                    prev_symbol = cur_prod[cur_symbol_id-1]
                    if prev_symbol not in nullables:
                        # do not check current symbol because previous not nullable
                        _next_prod(stack)
                        continue

                # do need to go deeper
                stack.append([cur_symbol, self.productions[cur_symbol], 0, 0])

    def _log_cur_prod(self, parse_stack, tokens):
        if not self._debug:
            return
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
        if not self._debug:
            return
        prefix = " "*(len(parse_stack) - 1)
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
                first_symbol = prod[0]
                if first_symbol is None:
                    # non_term -> None productions
                    for next_symbol in follow_sets[non_term]:
                        parse_table[(non_term, next_symbol)].append(prod)
                    continue
                if first_symbol in terminals:
                    parse_table[(non_term, first_symbol)].append(prod)
                    continue
                # first symbol in production is non-terminal
                firsts = first_sets[first_symbol]
                if non_term in nullables:
                    firsts.update(follow_sets[non_term])
                for first_symbol in firsts:
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
        return {
            symbol: [(None, ) if prod is None else prod for prod in prods]
            for symbol, prods in prods_map.items()
        }
