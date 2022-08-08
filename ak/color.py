"""Methods for printing colored text.

ColoredText - objects of this class are string-like objects, which can be
    converted to usual strings, containing color escape sequences.
    One of the problems with raw strings with escape sequences is that
    the length of the string is different from the number of printed
    characters. As a result it's not possible to use 'width' format
    specifier when formatting such strings.
    ColoredText objects can be printed using format specifiers.

ColorFmt - class which produces ColoredText objects.

ColorBytes - analog of ColorFmt, but for bytes.
    Both ColorFmt and ColorBytes produce a single mono-colored chunk, but
    - ColorFmt produces ColoredText - object which supports formatting and
      can be converted to str
    - ColorBytes produces simple bytes.

Example of usage:
    green_printer = ColorFmt('GREEN')
    t = green_printer("some green text") + " and normal text "
    t += [" and ", ColorFmt('RED')("some red text")]

    # produce string with color excape sequences
    str(t)
    # produce a string, which will take 100 places on screen
    f"{t: ^100}"

    # produce string with same text but no color escape sequences
    t_plain_text = t.plain_text()

    # print color examples table: each cell have different color/effects
    print(make_examples('text'))
"""

import re
from collections import namedtuple


#########################
# Color printer

class ColoredText:
    """Colored text. Consists of several mono-colored parts."""

    _ColoredChunk = namedtuple(
        '_ColoredChunk', ['c_prefix', 'text', 'c_suffix'])

    _SEQ_RE = None  # to be initialized on demand. Re matching any color sequence

    def __init__(self, *parts):
        """Construct colored text.

        Each arguments may be:
            - a simple string
            - another ColoredText object
        """
        self.scrlen = 0
        self.chunks = []  # list of _ColoredChunk
        for part in parts:
            self += part

    @classmethod
    def make(cls, color_prefix, text, color_suffix):
        """Construct ColoredText with explicit escape sequences."""
        return cls(cls._ColoredChunk(color_prefix, text, color_suffix))

    def __str__(self):
        # produce colored text
        return "".join(f"{p.c_prefix}{p.text}{p.c_suffix}" for p in self.chunks)

    def __len__(self):
        return self.scrlen

    def __eq__(self, other):
        """ColoredText objects are equal if have same text and same color.

        ColoredText with no color considered equal to raw string.
        """
        if self is other:
            return True

        if isinstance(other, ColoredText):
            if len(self.chunks) != len(other.chunks):
                return False
            return all(p0 == p1 for p0, p1 in zip(self.chunks, other.chunks))

        if isinstance(other, str):
            if len(self.chunks) != 1:
                return not self.chunks and not other

            p = self.chunks[0]
            return p.c_prefix == "" and p.text == other and p.c_suffix == ""

        return NotImplemented

    def plain_text(self) -> str:
        """produce simple str w/o color sequences."""
        return "".join(part.text for part in self.chunks)

    def __iadd__(self, other):
        """add some text (colored or usual) to self"""
        if isinstance(other, self._ColoredChunk):
            self._append_colored_chunk(other)
        elif isinstance(other, (list, tuple)):
            for part in other:
                self += part
        elif hasattr(other, 'chunks') and hasattr(other, 'scrlen'):
            # looks like this is another ColoredText object
            for part in other.chunks:
                self._append_colored_chunk(part)
        else:
            self._append_colored_chunk(self._ColoredChunk("", str(other), ""))

        return self

    @classmethod
    def strip_colors(cls, text: str) -> str:
        """Colorer-formatted string -> same string w/o coloring."""
        if cls._SEQ_RE is None:
            cls._SEQ_RE = re.compile("\033\\[[;\\d]*m")

        return re.sub(cls._SEQ_RE, "", text)

    def __add__(self, other):
        """Concatenate color text objects"""
        result = ColoredText(self)
        result += other
        return result

    def join(self, iterable):
        """Similar to str.join method.

        Elements of the iterable may be either strings or ColoredText objects.
        """
        result = ColoredText()
        is_first = True
        for chunk in iterable:
            if is_first:
                is_first = False
            else:
                result += self
            result += chunk

        return result

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

    def __getitem__(self, index) -> 'ColoredText':
        """Returns a slice of colored text.

        Examples:
        text[n]      - returns ColoredText with a single visible character.
                       raises exception if the index is out or range
        text[n:m]    - returns ColoredText with m - n printable characters or
                       an empty ColoredText if n >= n
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
            return ColoredText(
                self._copy_chunk(cur_chunk, cur_chunk.text[chunk_pos]))

        if not isinstance(index, slice):
            raise ValueError(
                f"Unexpected index value {index} of type {type(index)}. "
                f"Expected int or slice.")

        if index.step is not None:
            raise ValueError(
                "step is not supported by indexes of ColoredText")

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
            return ColoredText()

        # normal scenario: return actual colored substring
        chunk_id, chunk_pos = self._get_chunk_pos(start_pos)
        if chunk_id is None:
            return ColoredText()  # start_pos is out of range

        cur_chunk = self.chunks[chunk_id]
        cur_chunk = self._copy_chunk(cur_chunk, cur_chunk.text[chunk_pos:])

        new_chunks = []
        while remain_len > 0:
            if remain_len <= len(cur_chunk.text):
                new_chunks.append(
                    self._copy_chunk(cur_chunk, cur_chunk.text[:remain_len]))
                remain_len = 0
                break
            new_chunks.append(cur_chunk)
            remain_len -= len(cur_chunk.text)
            chunk_id += 1
            if chunk_id < len(self.chunks):
                cur_chunk = self.chunks[chunk_id]
            else:
                break  # index.stop position was out of range, but it's ok

        return ColoredText(*new_chunks)

    def fixed_len(self, desired_len):
        """Return new ColoredText which has specified length.

        Result is either truncated or padded with spaces original.
        """
        len_diff = desired_len - len(self)
        if len_diff < 0:
            return self[:desired_len]
        if len_diff > 0:
            return self + " "*len_diff
        return self

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

    def _append_colored_chunk(self, chunk):
        # append _ColoredChunk to self
        if not chunk.text:
            # It is safe to skip chunks with empty text.
            # It is expected that when we start printing new colored chunk
            # terminal is in default state. In this case printing c_prefix
            # followed by c_suffix has no visible effect and leaves terminal
            # in the same (default) state.
            return
        if self.chunks and chunk.c_prefix == self.chunks[-1].c_prefix:
            # merge with previous chunk
            prev_chunk = self.chunks[-1]
            self.chunks[-1] = self._copy_chunk(
                prev_chunk, prev_chunk.text + chunk.text)
        else:
            self.chunks.append(chunk)
        self.scrlen += len(chunk.text)

    @classmethod
    def _copy_chunk(cls, orig_chunk, new_text):
        # make a new _ColoredChunk with specified text and format sequences
        # same as in orig_chunk
        return cls._ColoredChunk(orig_chunk.c_prefix, new_text, orig_chunk.c_suffix)


class Palette:
    """Simple mapping 'syntax_name' -> ColorFmt"""

    def __init__(self, colors, use_colors=True):
        self.colors = colors.copy()
        self.use_colors = use_colors

    def get_color(self, syntax_name):
        """syntax_name -> ColorFmt"""
        no_effects_fmt = ColorFmt.get_plaintext_fmt()

        if not self.use_colors:
            return no_effects_fmt

        return self.colors.get(syntax_name, no_effects_fmt)


class ColorSequences:
    """Constructor of color escape sequences"""

    _COLORS = {
        'BLACK'  : "30",
        'RED'    : "31",
        'GREEN'  : "32",
        'YELLOW' : "33",
        'BLUE'   : "34",
        'MAGENTA': "35",
        'CYAN'   : "36",
        'WHITE'  : "37",
    }

    @classmethod
    def make(cls, color, bg_color=None,
             bold=None, faint=None, underline=None, blink=None, crossed=None,
             use_effects=True, make_bytes=False):
        """Make prefix and suffix to decorate text with specified effects.

        Arguments:
            most arguments are self-explained.
            - use_effects: if False, all other arguments are ignored and
                empty strings are returned.
            - make_bytes: produce bytes instead of strings
        """
        if color is not None and color not in cls._COLORS:
            raise ValueError(
                f"Invalid color name '{color}' specified. "
                f"Valid color names: {cls._COLORS.keys()}")
        if bg_color is not None and bg_color not in cls._COLORS:
            raise ValueError(
                f"Invalid bg_color name '{bg_color}' specified. "
                f"Valid color names: {cls._COLORS.keys()}")

        color_codes = []
        if use_effects:
            if color is not None:
                color_codes.append(cls._COLORS[color])

            if bg_color is not None:
                color_codes.append("4" + cls._COLORS[bg_color][1:])

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
            - color: one of ['BLACK', 'RED', 'GREEN', 'YELLOW', 'BLUE', 'MAGENTA',
                'CYAN', 'WHITE', None]
                None - does not change color
            - use_effects: if False, all other arguments are ignored and
                created object is 'dummy' - it does not add any effects to text.
        """
        self._color_prefix, self._color_suffix = ColorSequences.make(
            color, bg_color, bold, faint, underline, blink, crossed,
            use_effects)

    @classmethod
    def make(cls, color_obj, use_colors=True):
        """Helper method which produce ColorFmt object.

        Arguments:
        - color_obj: can be either:
            - ColorFmt object.
            - color name string
            - tuple of ("color name", {effect_name: value}).
              Check ColorFmt constructor for possible values of color
              and effects.
            - None (to use text w/o any effects)
        - use_colors: if False, the first argument is ignored and dummy
            ColorFmt object is returned (it produces text w/o any effects)
        """
        if not use_colors:
            return cls.get_plaintext_fmt()
        elif isinstance(color_obj, cls):
            return color_obj
        elif isinstance(color_obj, str):
            return cls(color_obj)
        elif isinstance(color_obj, tuple):
            assert len(color_obj) == 2, (
                f"Invalid argument(s) for ColorFmt: {color_obj}. "
                f"Expected tuple of two elements: color_name and dict."
            )
            return cls(color_obj[0], **color_obj[1])
        elif color_obj is None:
            return cls.get_plaintext_fmt()

        raise ValueError(f"Invalid arg {color_obj} for ColorFmt")

    @classmethod
    def get_plaintext_fmt(cls):
        """Get dummy ColorFmt object (it produces text w/o any effects)."""
        if cls._NO_COLOR is None:
            cls._NO_COLOR = cls(None)
        return cls._NO_COLOR

    def __call__(self, text):
        """text -> colored text (ColoredText object)."""
        return ColoredText.make(self._color_prefix, text, self._color_suffix)


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
        self._color_prefix, self._color_suffix = ColorSequences.make(
            color, bg_color, bold, faint, underline, blink, crossed,
            use_effects, make_bytes=True)

    def __call__(self, bytes_text):
        return self._color_prefix + bytes_text + self._color_suffix


def make_examples(text="text"):
    """Produce color examples table (simple printable string)"""

    def _produce_lines():
        width = max(len(text), 15)
        first_col_width = 20
        fmt_opts = [
            ('--', {}),
            ('bold', {"bold": True}),
            ('faint', {'faint': True}),
            ('both', {'bold': True, 'faint': True}),
        ]

        cols_descr = 'Color \\ modifiers'
        header_str = f"{cols_descr:{first_col_width}}"
        for col_name, _ in fmt_opts:
            header_str += f"{col_name:^{width}}"
        yield header_str

        for color in [None, 'BLACK', 'RED', 'GREEN', 'YELLOW',
                      'BLUE', 'MAGENTA', 'CYAN', 'WHITE']:
            line = f"{str(color):{first_col_width}}"
            for col_name, opts in fmt_opts:
                colored_text = ColorFmt(color, **opts)(text)
                line += f"{colored_text:^{width}}"
            yield line

    return "\n".join(line for line in _produce_lines())
