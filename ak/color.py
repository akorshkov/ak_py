"""Methods for printing colored text.

ColoredText - objects of this class are string-like objects, which can be
    converted to usual strings, containing color escape sequences.
    One of the problems with raw strings with escape sequences is that
    the length of the string is different from the number of printed
    characters. As a result it's not possible to use 'width' format
    specifier when formatting such strings.
    ColoredText objects can be printed using format specifiers.

SHText - source data for ColoredText construction, it doesn't know
    actual color of parts of text, but only names of syntaxes.
    Preferred way to create ColoredText is to create SHText and
    convert it to ColoredText using Palette.

ColorFmt - produces simple (mono-colored) ColoredText objects.

Palette - contains mapping {'syntax_type': ColorFmt} and produces
    ColoredText objects from SHText.

ColorsConfig - supposed to contain global colors configuration for the whole
    application (so that it would be possible to configure all coloring in
    a single place). Palette objects should be initialized from this global
    config; it is available by ak.color.get_global_colors_config().
    Default ColorsConfig contains common syntax names used in ak package,
    check it out:
    print(ak.color.get_global_colors_config().c_fmt())

PaletteUser - may be used as a base for classes which create own Palette
    from global ColorsConfig (helps to postpone Palette creation until
    after the global ColorsConfig is initialized)

ColorBytes - analog of ColorFmt, but for bytes.
    Both ColorFmt and ColorBytes produce a single mono-colored chunk, but
    - ColorFmt produces ColoredText - object which supports formatting and
      can be converted to str
    - ColorBytes produces simple bytes.

Example of usage:
    green_printer = ColorFmt('GREEN')  # check doc for more options
    t = green_printer("some green text") + " and normal text "
    t += [" and ", ColorFmt('RED')("some red text")]

    # produce string with color excape sequences
    str(t)
    # produce a string, which will take 100 places on screen
    f"{t: ^100}"

    # produce string with same text but no color escape sequences
    t_plain_text = t.plain_text()

Colors examples:
    use bin/colors_demo.py script to print examples of colored text.
"""

import re
from dataclasses import dataclass

from typing import Iterator


#########################
# Color printer

class _CTText:
    # 'Chunked Typed Text' - text, consisting of chunks with
    # different properties

    __slots__ = 'scrlen', 'chunks'

    @dataclass(frozen=True)
    class _Chunk:
        # chunk of text with a specified property
        syntax: str
        text: str

        @classmethod
        def make_plain(cls, text):
            """chunk of plain text - no property is associated with it"""
            return cls("", text)

        def is_plain(self) -> bool:
            """if chunk corresponds to 'plain' text"""
            return not self.syntax

        def clone(self, new_text):
            """create new chunk with same type but different text"""
            return type(self)(self.syntax, new_text)

        def has_same_type(self, other) -> bool:
            """if other chunk has same type"""
            return self.syntax == other.syntax

    def __init__(self, *parts):
        """Construct Chunked Typed Text.

        Each arguments may be:
          - a simple string
          - another object of this class
          - (for private use) - _Chunk or list of _Chunk objects
        """
        self.scrlen = 0
        self.chunks = []
        for part in parts:
            self += part

    @classmethod
    def make(cls, chunks_list):
        """Optimized constructor for internal use.

        The argument must be list of _Chunk objects. Consequent chunks are
        merged if they have the same 'syntax' property.
        """
        chunks_list = cls._merge_chunks(chunks_list)
        result = cls()
        result.scrlen = sum(len(c.text) for c in chunks_list)
        result.chunks = chunks_list
        return result

    @classmethod
    def _merge_chunks(cls, chunks_list):
        # merge _Chunk objects having the same 'syntax'.
        # may return the argument if there are no chunks to merge.
        need_merge = any(
            c.syntax == next_c.syntax
            for c, next_c in zip(chunks_list[:-1], chunks_list[1:]))

        if not need_merge:
            return chunks_list

        result = []
        cur_chunk = chunks_list[0]
        for chunk in chunks_list[1:]:
            if cur_chunk.syntax != chunk.syntax:
                result.append(cur_chunk)
                cur_chunk = chunk
            else:
                cur_chunk = cls._Chunk(cur_chunk.syntax, cur_chunk.text + chunk.text)
        result.append(cur_chunk)
        return result

    def __str__(self):
        # defaults implementation just concatenates text of all parts.
        # derived classes should produce rich text if there is enouth information
        # for it
        return self.plain_text()

    def plain_text(self) -> str:
        """produce simple str w/o color sequences."""
        return "".join(part.text for part in self.chunks)

    def __len__(self):
        return self.scrlen

    def __eq__(self, other):
        """Chunked Typed Text objects are equal if have same text and same type.

        _CTText with plain chunk type is considered equal to raw string.
        """
        if self is other:
            return True

        if isinstance(other, type(self)):
            if len(self.chunks) != len(other.chunks):
                return False
            return all(p0 == p1 for p0, p1 in zip(self.chunks, other.chunks))

        if isinstance(other, str):
            if len(self.chunks) != 1:
                return not self.chunks and not other

            p = self.chunks[0]
            return p.is_plain() and p.text == other

        return NotImplemented

    def __iadd__(self, other):
        """add some text (of a given type or 'plain') to self"""
        if isinstance(other, self._Chunk):
            self._append_chunk(other)
        elif isinstance(other, (list, tuple)):
            for part in other:
                self += part
        elif isinstance(other, type(self)):
            for part in other.chunks:
                self._append_chunk(part)
        else:
            self._append_chunk(self._Chunk.make_plain(str(other)))

        return self

    def __add__(self, other):
        """Concatenate sh_text objects"""
        result = type(self)(self)  # clone self
        result += other
        return result

    def join(self, iterable):
        """Similar to str.join method.

        Elements of the iterable may be either strings or TypedChunkedText objects.
        """
        result = type(self)()  # construct empty object
        is_first = True
        for chunk in iterable:
            if is_first:
                is_first = False
            else:
                result += self
            result += chunk

        return result

    def __getitem__(self, index) -> '_CTText':
        """Returns a slice of TypedChunkedText.

        Examples:
        text[n]      - returns TypedChunkedText with a single visible character.
                       raises exception if the index is out or range
        text[n:m]    - returns TypedChunkedText with m - n printable characters or
                       an empty TypedChunkedText if n >= n
                       Both n and m may be negative - behavior is the same as
                       when slicing a string or list.
        text[::2]    - not supported, exception will be raised.
        """
        if isinstance(index, int):
            orig_index_value = index
            if index < 0:
                index = self.scrlen + index
            chunk_id, chunk_pos = self._get_chunk_pos(index)
            if chunk_id is None:
                raise IndexError(f"Index {orig_index_value} is out of range")
            cur_chunk = self.chunks[chunk_id]
            return type(self)(cur_chunk.clone(cur_chunk.text[chunk_pos]))

        if not isinstance(index, slice):
            raise ValueError(
                f"Unexpected index value {index} of type {type(index)}. "
                f"Expected int or slice.")

        if index.step is not None:
            cls_name = type(self).__name__
            raise ValueError(
                f"step is not supported by indexes of {cls_name}")

        start_pos = index.start
        end_pos = index.stop

        if start_pos is None:
            start_pos = 0
        elif start_pos < 0:
            start_pos = max(0, self.scrlen + start_pos)

        if end_pos is None:
            end_pos = self.scrlen
        elif end_pos < 0:
            end_pos = max(0, self.scrlen + end_pos)

        remain_len = end_pos - start_pos
        if remain_len <= 0:
            return type(self)()

        # normal scenario: return actual TypedChunkedText 'substring'
        chunk_id, chunk_pos = self._get_chunk_pos(start_pos)
        if chunk_id is None:
            return type(self)()  # start_pos is out of range

        cur_chunk = self.chunks[chunk_id]
        cur_chunk = cur_chunk.clone(cur_chunk.text[chunk_pos:])

        new_chunks = []
        while remain_len > 0:
            if remain_len <= len(cur_chunk.text):
                new_chunks.append(cur_chunk.clone(cur_chunk.text[:remain_len]))
                remain_len = 0
                break
            new_chunks.append(cur_chunk)
            remain_len -= len(cur_chunk.text)
            chunk_id += 1
            if chunk_id < len(self.chunks):
                cur_chunk = self.chunks[chunk_id]
            else:
                break  # index.stop position was out of range, but it's ok

        return type(self)(*new_chunks)

    def fixed_len(self, desired_len):
        """Return new TypedChunkedText which has specified length.

        Result is either truncated or padded with spaces original.
        """
        len_diff = desired_len - len(self)
        if len_diff < 0:
            return self[:desired_len]
        if len_diff > 0:
            return self + " "*len_diff
        return self

    @classmethod
    def calc_chunks_len(cls, chunks) -> int:
        """[_Chunk, ] -> total len of the text in the chunks"""
        return sum(len(c.text) for c in chunks)

    @classmethod
    def resize_chunks_list(cls, chunks, new_len):  # -> [cls._Chunk]:
        """Truncates list of chunks or appends a chunk of empty text"""
        assert new_len >= 0
        existing_len = cls.calc_chunks_len(chunks)
        if existing_len == new_len:
            return chunks
        if existing_len < new_len:
            return chunks + [cls._Chunk("", " "*(new_len - existing_len))]
        remaining_len = new_len
        result = []
        for item in chunks:
            if remaining_len == 0:
                return result
            cur_item_len = len(item.text)
            if cur_item_len <= remaining_len:
                result.append(item)
                remaining_len -= cur_item_len
            else:
                result.append(cls._Chunk(item.syntax, item.text[:remaining_len]))
                remaining_len = 0
        result.append(cls._Chunk(""," "*remaining_len))
        return result

    def _get_chunk_pos(self, position):
        # position of visible character -> (chunk_id, char_pos_in_chunk)
        # (None, None) is returned if position is out of range
        if position < 0:
            return None, None
        for chunk_id, chunk in enumerate(self.chunks):
            if position < len(chunk.text):
                return chunk_id, position
            position -= len(chunk.text)
        return None, None  # position >= total length

    def _append_chunk(self, chunk):
        # append _Chunk to self
        if not chunk.text:
            # It is safe to skip chunks with empty text.
            # It is expected that when we start printing new typed chunk
            # terminal is in default state. In this case printing c_prefix
            # followed by c_suffix has no visible effect and leaves terminal
            # in the same (default) state.
            return
        if self.chunks and chunk.has_same_type(self.chunks[-1]):
            # merge with previous chunk
            prev_chunk = self.chunks[-1]
            self.chunks[-1] = prev_chunk.clone(prev_chunk.text + chunk.text)
        else:
            self.chunks.append(chunk)
        self.scrlen += len(chunk.text)


class SHText(_CTText):
    """Syntax-Highlighted text.

    Direct creation of ColoredText in application code may be inconvenient
    bacause actual colors to be used depend on configuration and not
    not be easily available.

    Low-level code creates text specifying not names of actual colors, but
    names on syntaxes.

    sh_descr = SHText("Result is: ", ("OK", "success"), ". Grats!")

    Later on use Palette object to produce colored text:

    print(some_palette(sh_descr))
    """
    __slots__ = tuple()

    def __init__(self, *parts):
        """Construct SHText.

        Each arguments may be:
          - a simple string
          - another object of this class
          - (syntax_name, text) pair
        """
        super().__init__()

        for part in parts:
            self += self._mk_init_item(part)

    @classmethod
    def _mk_init_item(cls, part):
        # constructor helper
        if isinstance(part, (list, tuple)):
            # ("SYNTAX", "text") pair is expected
            if len(part) != 2:
                raise ValueError(
                    f'unexpected item: {part}. Expected ("SYNTAX", text) pair')
            syntax, text = part
            return cls._Chunk(syntax, text)
        return part


class SyntaxGroupsUser:
    """Base class for objects which produce SHText.

    Helps to specify names of syntax groups to be used when producing SHText.

    Derive the class which produces SHText from SyntaxGroupsUser to override
    the default names of the syntax groups in SHText objects it produces.
    """
    _SYNTAX_GROUPS_NAMES = None

    @classmethod
    def make_syntax_groups_names(cls, syntax_names, syntax_names_prefix):
        """Make the {syntax_id: syntax_name}.

        The result is based on defaults _SYNTAX_GROUPS_NAMES and arguments.

        Arguments:
        - syntax_names: (optional) {syntax_id: overridden_syntax_name}
        - syntax_names_prefix: (optional) prefix to add to default syntax names.
        """
        assert cls._SYNTAX_GROUPS_NAMES is not None, (
            f"_SYNTAX_GROUPS_NAMES not specified in SyntaxGroupsUser-derived "
            f"class {cls}")
        if syntax_names is None and  syntax_names_prefix is None:
            return cls._SYNTAX_GROUPS_NAMES

        if syntax_names is None:
            syntax_names = {}
        return {
            syntax_id : syntax_names.get(
                syntax_id,
                dflt_syntax_name if syntax_names_prefix is None
                    else f"{syntax_names_prefix}.{dflt_syntax_name}")
            for syntax_id, dflt_syntax_name in cls._SYNTAX_GROUPS_NAMES.items()
        }


class ColoredText(_CTText):
    """Colored text. Consists of several mono-colored parts."""

    __slots__ = tuple()

    @dataclass(frozen=True)
    class _Chunk:
        # chunk of colored text
        c_prefix: str
        text: str
        c_suffix: str

        @classmethod
        def make_plain(cls, text):
            """chunk of plain (not colored) text"""
            return cls("", text, "")

        def is_plain(self) -> bool:
            """if chunk corresponds to plain (not colored) text"""
            return not self.c_prefix

        def clone(self, new_text):
            """create new chunk with same color but different text"""
            return type(self)(self.c_prefix, new_text, self.c_suffix)

        def has_same_type(self, other) -> bool:
            """if other chunk has same color"""
            return self.c_prefix == other.c_prefix

    _SEQ_RE = None  # to be initialized on demand. Re matching any color sequence

    @classmethod
    def _make_chunk(cls, color_prefix, text, color_suffix):
        # Construct 'single-chunk' ColoredText with explicit escape sequences.
        return cls._Chunk(color_prefix, text, color_suffix)

    def __str__(self):
        # produce colored text
        return "".join(f"{p.c_prefix}{p.text}{p.c_suffix}" for p in self.chunks)

    @classmethod
    def strip_colors(cls, text: str) -> str:
        """Colorer-formatted string -> same string w/o coloring."""
        if cls._SEQ_RE is None:
            cls._SEQ_RE = re.compile("\033\\[[;\\d]*m")

        return re.sub(cls._SEQ_RE, "", text)

    def __format__(self, format_spec):
        """Support formatted printing.

        Argument:
            - format_spec: [[fill]align][width][type]

        Examples:
            f"{x:10}"    -> "text      "
            f"{x:_^10}"  -> "___text___"
        """
        # validate format type specifier if present
        if format_spec:
            last_ch = format_spec[-1]
            if not last_ch.isdigit() and last_ch not in ('>', '<', '^'):
                # last character is format type. Only 's' is supported.
                if last_ch != 's':
                    raise ValueError(
                        f"Can't format ColoredText object: "
                        f"invalid format type '{last_ch}' specified")
                format_spec = format_spec[:-1]

        # detect align_char position
        align_ch_pos = -1
        align_char = '<'  # this is default behavior
        i = min(1, len(format_spec)-1)  # max expected position of align char
        while i >= 0:
            ch = format_spec[i]
            if ch in ('>', '<', '^'):
                align_ch_pos = i
                align_char = ch
                break
            i -= 1

        # read width
        width_part = format_spec[align_ch_pos+1:]
        width = 0
        if width_part:
            try:
                width = int(width_part)
            except ValueError as err:
                raise ValueError(
                    f"Can't format ColoredText object: "
                    f"invalid width '{width_part}' specified"
                ) from err

        # read fill character
        filler_ch = format_spec[0] if align_ch_pos == 1 else ' '

        # prepare filler prefix and suffix
        filler_width = max(width - self.scrlen, 0)
        if not filler_width:
            return str(self)
        elif align_char == '<':
            return str(self) + filler_ch*filler_width
        elif align_char == '>':
            return filler_ch*filler_width + str(self)
        else:
            prefix_width = filler_width // 2
            suffix_width = filler_width - prefix_width
            return filler_ch*prefix_width + str(self) + filler_ch*suffix_width


class _ColorSequences:
    # Constructor of color escape sequences

    _COLORS = {
        'BLACK'  : "0",
        'RED'    : "1",
        'GREEN'  : "2",
        'YELLOW' : "3",
        'BLUE'   : "4",
        'MAGENTA': "5",
        'CYAN'   : "6",
        'WHITE'  : "7",
    }

    @classmethod
    def make(cls, color, bg_color=None,
             bold=None, faint=None, underline=None, blink=None, crossed=None,
             use_effects=True, make_bytes=False):
        # Make prefix and suffix to decorate text with specified effects.
        #
        # Check ColorFmt doc for arguments description

        color_codes = []
        if use_effects:
            if color is not None:
                color_codes.append(cls._make_seq_element(color, False))

            if bg_color is not None:
                color_codes.append(cls._make_seq_element(bg_color, True))

            if bold:
                color_codes.append("1")

            if faint:
                color_codes.append("2")

            if underline:
                color_codes.append("4")

            if blink:
                color_codes.append("5")

            if crossed:
                color_codes.append("9")

        if color_codes:
            color_prefix = "\033[" + ";".join(c for c in color_codes) + "m"
            color_suffix = "\033[0m"
        else:
            color_prefix = ""
            color_suffix = ""

        if make_bytes:
            color_prefix = color_prefix.encode()
            color_suffix = color_suffix.encode()

        return color_prefix, color_suffix

    @classmethod
    def _make_seq_element(cls, color, is_bg=False):
        # create a part of the color escape sequence, the part which defines color

        fg_bg_id = "4" if is_bg else "3"
        param_name = "bg_color" if is_bg else "color"

        # case 1: 'color' is a name of color
        if color in _ColorSequences._COLORS:
            return fg_bg_id + _ColorSequences._COLORS[color]

        # case 2: 'color' is an (r, g, b) tuple, each compnent in range(5)
        if isinstance(color, (list, tuple)):
            if len(color) != 3 or any(c < 0 or c > 5 for c in color):
                raise ValueError(
                    f"Invalid {param_name} description tuple {color}. "
                    f"Valid color description tuple should have 3 elements "
                    f"each in range(5)")
            # tuple corresponds to an int color, will be handled in case 4.
            r, g, b = color
            color = 16 + r * 36 + g * 6 + b

        # case 3: color specifies shade of gray
        if isinstance(color, str):
            if color.startswith('g'):
                try:
                    shade = int(color[1:])
                except ValueError:
                    shade = -1
                if shade < 0 or shade > 24:
                    raise ValueError(
                        f"Invalid 'shade of gray' color description '{color}'. "
                        f"It is supposed to be in form 'g0' - 'g23'")
                color = 232 + shade
            else:
                raise ValueError(
                    f"Invalid {param_name} name '{color}'. "
                    f"Should be one of {list(cls._COLORS.keys())} "
                    f"or in form 'g0' - 'g23' for shades of gray")

        # case 4: 'color' is an int id of color
        if isinstance(color, int):
            if color < 0 or color > 255:
                raise ValueError(
                    f"Invalid int {param_name} id {color}. Valid int color id "
                    f"should be in range(256)")
            return f"{fg_bg_id}8:5:{color}"

        raise ValueError(f"Invalid {param_name} object: {type(color)}: {color!r}")


class ColorFmt:
    """Objects of this class produce text with specified color."""

    __slots__ = '_color_prefix', '_color_suffix'

    _NO_COLOR = None  # dummy ColorFmt object, will be initialized on demand

    def __init__(
            self, color, *, bg_color=None,
            bold=None, faint=None, underline=None, blink=None, crossed=None,
            use_effects=True):
        """Create an object which converts text to text with specified effects.

        Arguments:
        most arguments are self-explained.
        - color and bg_color: define text color and background color. It may be:
          - one of ['BLACK', 'RED', 'GREEN', 'YELLOW', 'BLUE', 'MAGENTA',
            'CYAN', 'WHITE', None]
          - integer color code: in range(256)
          - (r, g, b): tuple of 3 integers in range(5). Corresponds to
            integer color code 16 + r*36 + g*6 + b
          - string in form 'g0' - 'g23' - indicates shade of gray. Corresponds to
            integer color codes 231-255.
        - use_effects: if False, all other arguments are ignored and
            created object is 'dummy' - it does not add any effects to text.
        """
        self._color_prefix, self._color_suffix = _ColorSequences.make(
            color, bg_color, bold, faint, underline, blink, crossed,
            use_effects)

    @classmethod
    def get_plaintext_fmt(cls):
        """Get dummy ColorFmt object (it produces text w/o any effects)."""
        if cls._NO_COLOR is None:
            cls._NO_COLOR = cls(None)
        return cls._NO_COLOR

    def __call__(self, text):
        """text -> colored text (ColoredText object)."""
        return ColoredText(self._make_colored_chunk(text))

    def _make_colored_chunk(self, text) -> ColoredText._Chunk:
        return ColoredText._make_chunk(self._color_prefix, text, self._color_suffix)


class ColorBytes:
    """Objects of this class produce bytes with color sequences."""

    __slots__ = '_color_prefix', '_color_suffix'

    def __init__(
            self, color, *, bg_color=None,
            bold=None, faint=None, underline=None, blink=None, crossed=None,
            use_effects=True):
        """Create an object which decorates bytes color sequences.

        Arguments:
            most arguments are self-explained.
            - use_effects: if False, all other arguments are ignored and
                created object is 'dummy' - it does not add any effects to text.
        """
        self._color_prefix, self._color_suffix = _ColorSequences.make(
            color, bg_color, bold, faint, underline, blink, crossed,
            use_effects, make_bytes=True)

    def __call__(self, bytes_text):
        return self._color_prefix + bytes_text + self._color_suffix


#########################
# Palette and ColorsConfig

class Palette:
    """Simple mapping 'syntax_name' -> ColorFmt"""

    def __init__(self, colors, use_colors=True):
        """Create simple dictionary {syntax_type: ColorFmt}.

        Example:
            Palette({'syntax1': ColorFmt('RED'), 'syntax2': ColorFmt('BLUE')})
        """
        self.colors = colors.copy()
        self.use_colors = use_colors

    def make_report(self) -> str:
        """Create report of colors in in th palette"""
        return "\n".join(
            str(line) for line in self.gen_report_lines())

    def gen_report_lines(self) -> Iterator[str]:
        for syntax_name, color_fmt in sorted(self.colors.items()):
            yield f"{syntax_name:15}: {color_fmt('<SAMPLE>')}"

    def get_color(self, syntax_name):
        """syntax_name -> ColorFmt"""
        no_effects_fmt = ColorFmt.get_plaintext_fmt()

        if not self.use_colors:
            return no_effects_fmt

        return self.colors.get(syntax_name, no_effects_fmt)

    def __getitem__(self, index):
        """same behavior as get_color method"""
        return self.get_color(index)

    def __call__(self, *items) -> ColoredText:
        """Produce multi-colored ColoredText.

        Arguments:
        - items: each item me be
          - plain text
          - SHText
          - ('syntax_name', 'text')
          - ColoredText
        """
        result = ColorFmt.get_plaintext_fmt()('')
        for item in items:
            result += self._item_to_colored_text(item)
        return result

    def _item_to_colored_text(self, item):
        # process single item of __call__
        # produce item, which can be used to construct ColoredText
        if isinstance(item, ColoredText):
            return item
        if isinstance(item, SHText):
            return [
                self.get_color(chunk.syntax)._make_colored_chunk(chunk.text)
                for chunk in item.chunks]
        elif isinstance(item, (list, tuple)):
            if len(item) != 2:
                raise ValueError(
                    f"invalid syntax text item {item}. "
                    f"expected pair ('syntax_name', 'text')")
            syntax_name, text = item
            return self.get_color(syntax_name)(text)

        return ColorFmt.get_plaintext_fmt()._make_colored_chunk(item)


_COLORS_CONFIG = None  # initialized on-demand ColorsConfig-derived object
_GLOBAL_PALETTE = None


def get_global_colors_config():
    """Get global ColorsConfig"""
    global _COLORS_CONFIG
    if _COLORS_CONFIG is None:
        _COLORS_CONFIG = ColorsConfig({})  # all defaults
    return _COLORS_CONFIG


def set_global_colors_config(colors_config):
    """Set global ColorsConfig"""
    global _COLORS_CONFIG, _GLOBAL_PALETTE
    _COLORS_CONFIG = colors_config
    if _COLORS_CONFIG is None:
        _GLOBAL_PALETTE = None
    else:
        _GLOBAL_PALETTE = _COLORS_CONFIG.make_palette()


def get_global_palette():
    """Get the Palette corresponding to the global colors config."""
    global _GLOBAL_PALETTE
    if _GLOBAL_PALETTE is None:
        _GLOBAL_PALETTE = get_global_colors_config().make_palette()
    return _GLOBAL_PALETTE


class ColorsConfig:
    """Colors configuration. Usually a global object.

    ColorsConfig contains colors for miscelaneous syntax items such as
    numbers in pretty-printed jsons or table borders. ColorsConfig creates
    Palette objects to be used by misc pretty-printers for producing
    colored text.

    Global ColorsConfig object is ak.color._COLORS_CONFIG. Use
    ak.color.get_global_colors_config() and ak.color.set_global_colors_config()
    to access this object.
    """

    _NO_EFFECTS_FMT = ColorFmt.get_plaintext_fmt()

    DFLT_CONFIG = {
        "TEXT": "",  # default text settings
        "NAME": "GREEN:bold",
        "ATTR": "YELLOW",
        "FUNC_NAME": "BLUE",
        "TAG": "GREEN",
        "CATEGORY": "MAGENTA",
        "KEYWORD": "BLUE:bold",
        "NUMBER": "YELLOW",
        "WARN": "RED",
        "OK": "GREEN:bold",
        "TABLE": {
            "BORDER": "GREEN",
            "COL_TITLE": "GREEN:bold",
            "NUMBER": "NUMBER",
            "KEYWORD": "KEYWORD",
            "WARN": "WARN",
        },
    }

    _MODIFIERS = {
        'bold': ('bold', True),
        'faint': ('faint', True),
        'underline': ('underline', True),
        'blink': ('blink', True),
        'crossed': ('crossed', True),
        'no_bold': ('bold', False),
        'no_faint': ('faint', False),
        'no_underline': ('underline', False),
        'no_blink': ('blink', False),
        'no_crossed': ('crossed', False),
    }

    _COLORS_NAMES = _ColorSequences._COLORS.keys() | {""}

    def __init__(self, *extra_rules, use_effects=True):
        """Constructor.

        Arguments:
        - extra_rules: dictionaries of amendments to default config (*)
        - use_effects: if False - ignores all other config settings and creates
          'no-color' config

        (*) example of extra_rules:
        {
            "NAME": "BLUE:bold",
            "TABLE": {
                "NAME": "YELLOW",
                "BORDER": "GREEN",
                "NUMBER": "TABLE.NAME",
            }
        }

        Color description format:
            "COLOR/BG_COLOR:modifiers"
        or
            "OTHER_SYNTAX:modifiers"

        where modifiers is a list of individual modifiers with optional 'no_' prefix.

        Examples:
            "YELLOW/BLUE:bold,faint,underline,blink,crossed"
            "GREEN"
            "RED:bold"
            "OTHER_SYNTAX_NAME:no_bold"

        Check ColorsConfig.DFLT_CONFIG for names of syntaxes.
        """
        self.flat_init_conf = self._flatten_dict(self.DFLT_CONFIG)
        for additional_syntax in extra_rules:
            self.flat_init_conf.update(self._flatten_dict(additional_syntax))

        if not use_effects:
            # no colors formatting will be used - and do not even try to parse
            # config data
            self.all_formats = {}
            return

        # {syntax_name: (color_name, other_syntax_name, modifiers)}
        flat_init_data = {
            syntax_name: self._parse_color_descr(color_descr)
            for syntax_name, color_descr in self.flat_init_conf.items()
        }

        # now flat_init_data contains init params for colors. These rules may
        # refer to other rules. Resolve these dependencies.
        syntax_attrs = {}  # {syntax_name: (color_name, modifiers)}
        for syntax_name, value in flat_init_data.items():
            color_name, src_syntax_name, modifiers = value
            assert color_name is None or src_syntax_name is None
            if syntax_name in syntax_attrs:
                # rules for this syntax_name processed already
                continue
            path = []
            while True:
                if src_syntax_name is None:
                    # source syntax can be processed immediately
                    syntax_attrs[syntax_name] = (color_name, modifiers)
                    break
                path.append((syntax_name, src_syntax_name, modifiers))
                if src_syntax_name in syntax_attrs:
                    # source syntax is ready
                    break
                if src_syntax_name not in flat_init_data:
                    raise Exception(
                        f"Invalid colors config: rule for syntax '{syntax_name}' "
                        f"referenses syntax '{src_syntax_name}' which does not exist")
                # need to go deeper
                color_name, next_src_syntax_name, modifiers = (
                    flat_init_data[src_syntax_name])

                syntax_name, src_syntax_name = src_syntax_name, next_src_syntax_name
                assert color_name is None or src_syntax_name is None
                if any(syntax_name == x[0] for x in path):
                    # circular dependency detected
                    names_path = [x[0] for x in path]
                    names_path.append(syntax_name)
                    raise Exception(
                        f"circular syntax rules dependencies: {names_path}")

            # process all the rules accumulated in path
            for syntax_name, src_syntax_name, modifiers in path[::-1]:
                assert src_syntax_name in syntax_attrs
                src_color, src_modifiers = syntax_attrs[src_syntax_name]
                results_modifiers = src_modifiers.copy()
                results_modifiers.update(modifiers)
                syntax_attrs[syntax_name] = (src_color, results_modifiers)

        # syntax_attrs contains color="" in 'plaintext' case, but ColorFmt
        # expects None. Fix this:
        fix_empty_color = lambda color: None if color == "" else color

        self.all_formats = {
            syntax_name: ColorFmt(fix_empty_color(color), **modifiers)
            for syntax_name, (color, modifiers) in syntax_attrs.items()
        }

    @classmethod
    def _parse_color_descr(cls, color_descr):
        # parse string description of a color
        # color_descr_srt -> (color_name, other_syntax_name, modifiers)
        color_name = None
        bk_color_name = None
        other_item_name = None
        modifiers = {}

        chunks = color_descr.split(':')
        assert len(chunks) < 3, f"invalid color description: '{color_descr}'"
        if len(chunks) == 1:
            chunks.append("")

        color_part, modifiers_part = chunks

        # process color_part
        chunks = color_part.split('/')
        assert len(chunks) < 3, f"invalid color name '{color_part}'"
        if len(chunks) == 2:
            # "COLOR/BK_COLOR"
            color_name, bk_color_name = chunks
            assert color_name in cls._COLORS_NAMES, (
                f"invalid color name '{color_name}'")
            assert bk_color_name in cls._COLORS_NAMES, (
                f"invalid color name '{bk_color_name}'")
        else:
            if chunks[0] in cls._COLORS_NAMES:
                color_name = chunks[0]
            else:
                # this is not a color name, but other syntax name
                other_item_name = chunks[0]

        # process modiiers part
        chunks = [s.strip() for s in modifiers_part.split(',')]
        chunks = [s for s in chunks if s]
        for modifier in chunks:
            try:
                mod_name, mod_value = cls._MODIFIERS[modifier]
            except KeyError:
                raise Exception(f"invalid color modifier name '{modifier}'")
            modifiers[mod_name] = mod_value

        if bk_color_name is not None:
            modifiers['bg_color'] = bk_color_name

        return color_name, other_item_name, modifiers

    @classmethod
    def _flatten_dict(cls, src):
        # transform structure of nested dictionaries into a flat dictionary.
        # keys of items corresponding to elements of nested disctionaris are
        # composed of names of items in path:
        # {'TABLE': {'BORDER': value}}  ->  {'TABLE.BORDER': value}
        result = {}
        for key, value in src.items():
            if isinstance(value, str):
                result[key] = value
            elif isinstance(value, dict):
                flatten_subdict = cls._flatten_dict(value)
                for skey, sval in flatten_subdict.items():
                    result[f"{key}.{skey}"] = sval
        return result

    def get_color(self, syntax_name) -> ColorFmt:
        """syntax_name -> ColorFmt"""
        return self.all_formats.get(syntax_name, self._NO_EFFECTS_FMT)

    def make_palette(self, group_name=None, **kwargs) -> Palette:
        """Creates Palette object for a specified syntax group.

        For example, for syntax group 'TABLE' the default ColorsConfig will produce
        Palette with following items:
            "BORDER", "COL_TITLE", "NUMBER", "KEYWORD", "WARN"

        Additional amendments to palette colors may be specified in kwargs.
        kwargs format:
        "PALETTE_SYNTAX_NAME": "CONF_SYNTAX_NAME"
        """
        prefix = "" if group_name is None else group_name + "."
        prefix_len = len(prefix)
        palette_colors = {}
        for full_syntax_name, color_fmt in self.all_formats.items():
            if not full_syntax_name.startswith(prefix):
                continue
            syntax_name = full_syntax_name[prefix_len:]
            palette_colors[syntax_name] = color_fmt

        for syntax, conf_syntax in kwargs.items():
            palette_colors[syntax] = self.get_color(conf_syntax)

        return Palette(palette_colors)

    def make_report(self) -> str:
        """Create colored report of self."""
        return "\n".join(self.gen_report_lines())

    def gen_report_lines(self) -> Iterator[str]:
        """Generate lines for self-report"""
        offset_step = "  "
        common_path = []  # path to a current syntax element
        for syntax_name, syntax_descr in sorted(self.flat_init_conf.items()):
            if not syntax_descr:
                syntax_descr = "<SAMPLE>"
            syntax_chunks = syntax_name.split('.')
            cur_path = syntax_chunks[:-1]
            cur_name = syntax_chunks[-1]

            # leave only prefix of common_path which is still valid for current item
            cmn_path_valid_len = 0
            for cmn_path_chunk, synt_path_chunk in zip(common_path, cur_path):
                if cmn_path_chunk != synt_path_chunk:
                    break
                cmn_path_valid_len += 1
            common_path = common_path[:cmn_path_valid_len]

            while len(cur_path) > len(common_path):
                # report next group name
                depth = len(common_path)
                group_name = cur_path[depth]
                common_path.append(group_name)
                yield f"{offset_step*depth}{group_name} ->"

            assert len(cur_path) == len(common_path)
            # report the syntax description
            depth = len(common_path)
            prefix = self._NO_EFFECTS_FMT(offset_step*depth)
            color_fmt = self.get_color(syntax_name)
            yield str(prefix + f"{cur_name}: " + color_fmt(syntax_descr))


def sh_fmt(arg, *, palette=None) -> ColoredText:
    """Convert an argument to ColoredText using global colors config.

    Arguments:
    - arg: can be either
      - SHText
      - an object with 'sh_text' method
      - any object, that can be converted to string. Trivial formating is
        used in this case and so that no color sequences would be included
        into the final text.
    - palette: specify this argument if you want to use not the default palette
    """
    if palette is None:
        palette = get_global_palette()
    sh_text_attr = getattr(arg, 'sh_text', None)
    if sh_text_attr is not None:
        return palette(sh_text_attr())
    if isinstance(arg, SHText):
        return palette(arg)
    return palette(str(arg))


def sh_lines_fmt(sh_lines, palette=None) -> Iterator[ColoredText]:
    """Convert multiple SHText into ColoredText objects using global colors config."""
    if palette is None:
        palette = get_global_palette()
    for sh_text in sh_lines:
        yield palette(sh_text)


def sh_print(*args, palette=None, sep=' ', end='\n', file=None, flush=False):
    """Print colored text using global color config.

    Main purpose of the method is to print SHText or objects, that generate
    SHText (that is objects which have 'gen_sh_lines' or 'sh_text' methods)

    As the number of SHText lines generated by arg.gen_sh_lines() may be large
    this method prints each line as soon as it receives it.

    It prints all other objects the same way the standard 'print' does.
    """
    if palette is None:
        palette = get_global_palette()

    def _obj_to_print_items(obj):
        # do convert the argument to lines of colored text if possible
        sh_lines_attr = getattr(arg, 'gen_sh_lines', None)
        if sh_lines_attr is not None:
            for sh_text in sh_lines_attr():
                yield palette(sh_text)
            return
        sh_text_attr = getattr(arg, 'sh_text', None)
        if sh_text_attr is not None:
            yield sh_text_attr()
            return
        if isinstance(obj, SHText):
            yield palette(obj)
            return
        yield obj

    cur_line_args = []
    for arg in args:
        start_new_line = False
        for colored_text in _obj_to_print_items(arg):
            if start_new_line:
                print(*cur_line_args, sep=sep, end=end, file=file, flush=flush)
                cur_line_args = []
            cur_line_args.append(colored_text)
            start_new_line = True
    if cur_line_args:
        print(*cur_line_args, sep=sep, end=end, file=file, flush=flush)


class PaletteUser:
    """Base class for classes which construct Palette from global config.

    The global config is ColorsConfig object stored in ak.color._COLORS_CONFIG.

    PaletteUser-defived class T provide class method cls.get_palette() (and
    shorter synonim 'c_fmt()') which is supposed to be used by objects of T to get
    properly configured palette.

    Palette object returned by cls.get_palette() is created only once when
    this method is called first time. Make sure that the global colors
    config is initialized by that time. (That means that if application
    does not use default colors configuration, ColorsConfig should be configured
    as soon as possible, before get_palette() method of any PaletteUser-derived
    class is called).
    """

    _PALETTE = None  # Palette of a class will be stored here

    # _SYNTAX_GROUP may be specify in derived class.
    # syntaxes from this group will be used to create Palette for this class
    _SYNTAX_GROUP = None

    @classmethod
    def _init_palette(cls, _colors_config):
        # configure Palette for this class
        #
        # can be overridden in derived class
        #
        # method may return syntax group name or ready Palette object
        return "" if cls._SYNTAX_GROUP is None else cls._SYNTAX_GROUP

    @classmethod
    def _init_palette_impl(cls) -> Palette:
        # create Palette object based on _init_palette (which may be
        # re-implemented in derived class)
        global_colors_config = get_global_colors_config()
        init_data = cls._init_palette(global_colors_config)
        if isinstance(init_data, Palette):
            return init_data
        assert isinstance(init_data, str)
        return global_colors_config.make_palette(init_data)

    @classmethod
    def get_palette(cls) -> Palette:
        """Get Palette object to be used by an object of cls class."""
        if cls._PALETTE is None:
            cls._PALETTE = cls._init_palette_impl()
        assert cls._PALETTE is not None
        return cls._PALETTE

    @classmethod
    def c_fmt(cls) -> Palette:
        """shorter synonim for get_palette()"""
        return cls.get_palette()
