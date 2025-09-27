"""Methods for printing colored text.

CHText - objects of this class are string-like objects, which can be
    converted to usual strings, containing color escape sequences.
    One of the problems with raw strings with escape sequences is that
    the length of the string is different from the number of printed
    characters. As a result it's not possible to use 'width' format
    specifier when formatting such strings.
    CHText objects can be printed using format specifiers.

ColorFmt - produces CHText.Chunk object - optimized for a single color version
    of CHText.

Palette - contains mapping {'plt_synt_id': ColorFmt}

ColorsConfig - supposed to contain global colors configuration for the whole
    application (so that it would be possible to configure all coloring in
    a single place). Palette objects should be initialized from this global
    config; it is available by ak.color.get_global_colors_config().
    Default ColorsConfig contains common syntax names used in ak package,
    check it out:
    print(ak.color.get_global_colors_config().make_report())

PaletteUser - may be used as a base for classes which create own Palette
    from global ColorsConfig.

ColorBytes - analog of ColorFmt, but for bytes.
    Both ColorFmt and ColorBytes produce a single mono-colored chunk, but
    - ColorFmt produces CHText - object which supports formatting and
      can be converted to str
    - ColorBytes produces simple bytes.

Example of usage:
    green_fmt = ColorFmt('GREEN')  # check doc for more options
    t = green_fmt("some green text") + " and normal text "
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
# low-level implementation of colored text

class _ColorCodesSet:
    # Set of codes which affect the decoration of some part of text on screen.
    # Actualy using these codes it is possible to modify not only the colors but also
    # some other properties of the text (such as presence of underline)
    #
    # Decorated text looks like this:
    #
    # "\033[<CODES>mTHE TEXT\033[0m"
    #  -------------        -------
    #        |                closing escape sequence
    #  opening ansi escape sequence
    #
    # where <CODES> is a ';'-separated list of codes (without brackets).
    # Each code defines some aspect of text decoration (for example text color or
    # underline style) and is either a number or a ':'- or ';'-separated list of numbers.
    # Some examples of codes:
    # - 4     : underline text
    # - 4:2   : double underline
    # - 4:3   : curly underline
    #
    # Object of _ColorCodesSet class constructs and keeps codes used to format given text.
    # It keeps codes associated with different aspects of decoration separately
    # to make it possible to combine code sets.
    #
    # This class also serves as a constructor of color escape sequences: the arguments
    # of the methods of this class are supposed to be human-readable.

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

    # All the strings which can represent a color.
    # These are names of colors from _COLORS and shades of grey 'g0' - 'g23'
    # Values for the shades of grey are corresponding 256-color-codes
    _POSSIBLE_COLOR_NAME_STRINGS = {
        **{f"g{i}": 232 + i for i in range(24)},
        **_COLORS}

    _UNDERLINE_STYLES = {
        'SINGLE': "1",
        'DBL': "2",
        'CURL': "3",
        'DOT': "4",
        'DASH': "5",
    }

    # possible identificators of color subject. The identificator is the first char
    # of the color code and specifies what part of the text will have this color.
    # For example codes "36", "46" and "56" mean cyan color ("6") for text ("3"),
    # background ("4") and underline ("5") respectively.
    _COLORS_SUBJECTS = {
        '3': "text color",
        '4': "background color",
        '5': "underline color",
    }

    _N_COLOR_CODES = 7

    # set of color codes corresponding to "no decorations" format
    _NO_COLOR_CODES = tuple(None for _ in range(_N_COLOR_CODES))

    __slots__ = ('_ccodes', )

    def __init__(self, color_codes):
        """Internal constructor. Use _ColorCodesSet.make method as a constructor."""
        assert len(color_codes) == self._N_COLOR_CODES
        self._ccodes = color_codes

    def make_ansi_sequences(self, make_bytes=False) -> (str, str):
        """Returns opening and closing ansi-sequenses for text decoration."""
        if all(s is None for s in self._ccodes):
            prefix, suffix = "", ""
        else:
            prefix = "\033[" + ";".join(s for s in self._ccodes if s) + "m"
            suffix = "\033[0m"

        if make_bytes:
            prefix = prefix.encode()
            suffix = suffix.encode()

        return prefix, suffix

    @classmethod
    def make(cls, color, bg_color=None,
             bold=None, faint=None, underline=None, blink=None, crossed=None,
             no_color=False):
        """_ColorCodesSet constructor.

        Check ColorFmt doc for arguments description
        """
        if no_color:
            color_codes = cls._NO_COLOR_CODES
        else:
            color_codes = (
                cls._make_seq_element(color, "3"),
                cls._make_seq_element(bg_color, "4"),
                cls._make_simple_code(bold, "1"),
                cls._make_simple_code(faint, "2"),
                cls._make_underline_color_code(underline),
                cls._make_simple_code(blink, "5"),
                cls._make_simple_code(crossed, "9"),
            )

        return cls(color_codes)

    @classmethod
    def combine_color_code_sets(cls, color_codes_sets):
        """Constructor, combines several _ColorCodesSet objects into one."""
        result_ccodes = [None for _ in range(cls._N_COLOR_CODES)]
        for code_set in color_codes_sets:
            for i, ccode in enumerate(code_set._ccodes):
                if ccode is not None:
                    result_ccodes[i] = ccode
        return cls(result_ccodes)

    @classmethod
    def _make_simple_code(cls, bool_opt, value):
        # to be used to prepare the color code corresponding for a simple bool
        # text property (such as 'blink' or 'crossed')
        if bool_opt is None:
            return None
        return value if bool_opt else ""

    @classmethod
    def _make_underline_color_code(cls, opt_value):
        # constructor of the color code corresponding to the 'underline' aspect of decoration

        if opt_value is None:
            return None

        # Simple bool value: either single-underline with a text color or no underline
        if opt_value is False:
            return ""
        if opt_value is True:
            return "4"

        #  of the "underline" option may look like
        # "RED"                 - standard (single line) underline of RED color
        # (r, g, b)             - standard underline of specified color
        # "DBL"                 - double underline, same color as text
        # ("CURL", (r, g, b))   - curly underline of specified color

        if isinstance(opt_value, str):
            uline_style = cls._UNDERLINE_STYLES.get(opt_value)
            if uline_style is not None:
                # the option is just a style name
                color_arg = None
            else:
                # the option is just a color name
                if opt_value not in cls._POSSIBLE_COLOR_NAME_STRINGS:
                    raise ValueError(
                        f"Invalid underline style description '{opt_value}'. "
                        f"String value of this option must be either "
                        f"style ({cls._UNDERLINE_STYLES.keys()}) "
                        f"or color name ({cls._COLORS.keys()})"
                        f"or shade of color ('g0' - 'g23')")
                uline_style = cls._UNDERLINE_STYLES["SINGLE"]
                color_arg = opt_value
        elif isinstance(opt_value, (list, tuple)):
            if all(isinstance(c, int) for c in opt_value):
                # looks like a color tuple (r, g, b)
                uline_style = cls._UNDERLINE_STYLES["SINGLE"]
                color_arg = opt_value
            else:
                if len(opt_value) != 2:
                    raise ValueError(
                        f"Invalid underline style description '{opt_value}'")
                uline_style_name, color_arg = opt_value
                uline_style = cls._UNDERLINE_STYLES.get(uline_style_name)
                if uline_style is None:
                    raise ValueError(f"Invalid underline style name '{uline_style_name}'")
        elif isinstance(opt_value, int):
            # it must be a 256-color of the underline
            uline_style = cls._UNDERLINE_STYLES["SINGLE"]
            color_arg = opt_value
        else:
            raise ValueError(f"Invalid underline style '{opt_value}'")

        color_code = cls._make_seq_element(color_arg, "5")

        result_code = "4:" + uline_style
        if color_code is not None:
            result_code += ";" + color_code

        return result_code

    @classmethod
    def _make_seq_element(cls, color, color_subject):
        # create a part of the color escape sequence, the part which defines color
        # Arguments:
        # - color:
        #   check doc of the ColorFmt constructor for more details about possible formats
        # - color_sublect:
        #   "3" - foreground text color
        #   "4" - background color
        #   "5" - underline color

        if color is None:
            return None

        orig_color_arg = color

        param_name = cls._COLORS_SUBJECTS.get(color_subject)
        assert param_name is not None, f"{color_subject} must be in {cls._COLORS_SUBJECTS}"

        # case 1: 'color' is a name of color
        if color in _ColorCodesSet._COLORS:
            if color_subject == "5":
                # for some reason code of color of underline must be in 256-color format
                color = int(cls._COLORS[color])
            else:
                # simple color code. It looks like "s5" (where s in {"3", "4"})
                return color_subject + cls._COLORS[color]

        # case 2: 'color' is an (r, g, b) tuple, each component in range(5)
        if isinstance(color, (list, tuple)):
            if len(color) != 3 or any(c < 0 or c > 5 for c in color):
                raise ValueError(
                    f"Invalid {param_name} description tuple {orig_color_arg}. "
                    f"Valid color description tuple should have 3 elements "
                    f"each in range(5)")
            # tuple corresponds to an int color, will be handled in case 4.
            r, g, b = color
            color = 16 + r * 36 + g * 6 + b

        # case 3: color specifies shade of gray
        if isinstance(color, str):
            # str name of a color may be either one of in cls._COLORS or
            # a shade of grey. Names from cls._COLORS were processed previously.
            # Convert shade of grey to 256-color int
            color = cls._POSSIBLE_COLOR_NAME_STRINGS.get(color)
            if color is None:
                raise ValueError(
                    f"Invalid {param_name} name '{orig_color_arg}'. "
                    f"Should be one of {list(cls._COLORS.keys())} "
                    f"or in form 'g0' - 'g23' for shades of gray")

        # case 4: 'color' is an int id of color
        if isinstance(color, int):
            if color < 0 or color > 255:
                raise ValueError(
                    f"Invalid int {param_name} id {orig_color_arg}. Valid int color id "
                    f"should be in range(256)")
            return f"{color_subject}8:5:{color}"

        raise ValueError(
            f"Invalid {param_name} object: {type(orig_color_arg)}: {orig_color_arg!r}")


#########################
# CHText - colored text

@dataclass(frozen=True)
class _CHTextChunk:
    # Colored Text is stored not as string, but as a list of chunks. Each chunk
    # contains actual text (printable characters) and control sequences (prefix
    # and suffix). This class represents a single chunk.
    #
    # See description of CHText class for more information.
    #
    # _CHTextChunk is simply a part of CHText. It implements almost all the methods
    # of the CHText because for performance reasons some methods
    # of this module may produce _CHTextChunk instead of the CHText objects.

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

    def add_chunks_same_type(self, other):
        """Add chunks of the same type.

        Chunks are merged and a single chunk is returned.
        """
        assert self.has_same_type(other)
        return type(self)(self.c_prefix, self.text + other.text, self.c_suffix)

    # Methods which make _CHTextChunk behavior similar to CHText
    def __str__(self):
        # produce colored text
        return f"{self.c_prefix}{self.text}{self.c_suffix}"

    def plain_text(self):
        return self.text

    @classmethod
    def strip_colors(cls, text: str) -> str:
        """Colorer-formatted string -> same string w/o coloring."""
        return CHText.strip_colors(text)

    def __len__(self):
        return len(self.text)

    def __eq__(self, other):
        if self is other:
            return True

        if isinstance(other, type(self)):
            return (
                self.c_prefix == other.c_prefix
                and self.text == other.text
                and self.c_suffix == other.c_suffix)

        if isinstance(other, str):
            return self.is_plain() and self.text == other

        return NotImplemented

    def __iadd__(self, other) -> 'CHText':
        return CHText(self, other)

    def __add__(self, other) -> 'CHText':
        return CHText(self, other)

    def __radd__(self, other) -> 'CHText':
        return CHText(other, self)

    def join(self, iterable) -> 'CHText':
        sep = CHText(self)
        return sep.join(iterable)

    def __getitem__(self, index) -> '_CHTextChunk':
        return self.clone(self.text[index])

    def fixed_len(self, desired_len) -> 'CHText':
        len_diff = desired_len - len(self.text)
        if len_diff > 0:
            return CHText(self, " "*len_diff)
        if len_diff < 0:
            return CHText(self.clone(self.text[:desired_len]))
        return CHText(self)

    def __format__(self, format_spec):
        return CHText(self).__format__(format_spec)


class CHText:
    """Colored text. Consists of several mono-colored parts."""

    __slots__ = 'scrlen', 'chunks'

    Chunk = _CHTextChunk

    _SEQ_RE = None  # to be initialized on demand. Re matching any color sequence

    def __init__(self, *parts):
        """Construct Chunked Typed Text.

        Each arguments may be:
          - a simple string
          - another object of this class
          - (for private use) - Chunk or list of Chunk objects
        """
        self.scrlen = 0
        self.chunks = []
        for part in parts:
            self += part

    @classmethod
    def make(cls, chunks_list):
        """Optimized constructor for internal use.

        The argument must be list of Chunk objects. Consequent chunks are
        merged if they have the same 'syntax' property.
        """
        chunks_list = cls._merge_chunks(chunks_list)
        result = cls()
        result.scrlen = sum(len(c.text) for c in chunks_list)
        result.chunks = chunks_list
        return result

    def __str__(self):
        # produce colored text
        return "".join(f"{p.c_prefix}{p.text}{p.c_suffix}" for p in self.chunks)

    def plain_text(self) -> str:
        """produce simple str w/o color sequences."""
        return "".join(part.text for part in self.chunks)

    @classmethod
    def strip_colors(cls, text: str) -> str:
        """Colorer-formatted string -> same string w/o coloring."""
        if cls._SEQ_RE is None:
            cls._SEQ_RE = re.compile("\033\\[[;:\\d]*m")

        return re.sub(cls._SEQ_RE, "", text)

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

        if isinstance(other, self.Chunk):
            if len(self.chunks) == 0:
                return other.text == ""
            return len(self.chunks) == 1 and self.chunks[0] == other

        return NotImplemented

    def __iadd__(self, other):
        """add some text (of a given type or 'plain') to self"""
        if isinstance(other, self.Chunk):
            self._append_chunk(other)
        elif isinstance(other, (list, tuple)):
            for part in other:
                self += part
        elif isinstance(other, type(self)):
            need_merge = (
                len(self.chunks) > 0
                and len(other.chunks) > 0
                and self.chunks[-1].has_same_type(other.chunks[0]))

            if need_merge:
                self.chunks[-1] = self.chunks[-1].add_chunks_same_type(
                    other.chunks[0])
                self.chunks.extend(other.chunks[1:])
            else:
                self.chunks.extend(other.chunks)

            self.scrlen += other.scrlen
        else:
            self._append_chunk(self.Chunk.make_plain(str(other)))

        return self

    def __add__(self, other) -> 'CHText':
        """Concatenate CHText objects"""
        result = type(self)(self)  # clone self
        result += other
        return result

    def __radd__(self, other) -> 'CHText':
        """Concatenate in case CHText is the second operand."""
        return type(self)(other, self)

    def join(self, iterable):
        """Similar to str.join method.

        Elements of the iterable may be either strings or CTText objects.
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
        """Returns a slice of _CTText.

        Examples:
        text[n]      - returns _CTText with a single visible character.
                       raises exception if the index is out or range
        text[n:m]    - returns _CTText with m - n printable characters or
                       an empty _CTText if n >= n
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

        # normal scenario: return actual _CTText 'substring'
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
        """Return new _CTText which has specified length.

        Result is either truncated or padded with spaces original.
        """
        len_diff = desired_len - len(self)
        if len_diff < 0:
            return self[:desired_len]
        if len_diff > 0:
            return self + " "*len_diff
        return self

    def __format__(self, format_spec) -> str:
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
                        f"Can't format CHText object: "
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
                    f"Can't format CHText object: "
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

    @classmethod
    def calc_chunks_len(cls, chunks) -> int:
        """[Chunk, ] -> total len of the text in the chunks"""
        return sum(len(c.text) for c in chunks)

    @classmethod
    def resize_chunks_list(cls, chunks, new_len):  # -> [cls.Chunk]:
        """Truncates list of chunks or appends a chunk of empty text"""
        assert new_len >= 0
        existing_len = cls.calc_chunks_len(chunks)
        if existing_len == new_len:
            return chunks
        if existing_len < new_len:
            return chunks + [cls.Chunk.make_plain(" "*(new_len - existing_len))]
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
                result.append(item.clone(item.text[:remaining_len]))
                remaining_len = 0
        result.append(cls.Chunk.make_plain(" "*remaining_len))
        return result

    @classmethod
    def _merge_chunks(cls, chunks_list):
        # merge Chunk objects having the same 'syntax'.
        # may return the argument if there are no chunks to merge.

        need_merge = any(
            c.has_same_type(next_c)
            for c, next_c in zip(chunks_list[:-1], chunks_list[1:]))

        if not need_merge:
            return chunks_list

        result = []
        cur_chunk = chunks_list[0]
        for chunk in chunks_list[1:]:
            if not cur_chunk.has_same_type(chunk):
                result.append(cur_chunk)
                cur_chunk = chunk
            else:
                cur_chunk = cur_chunk.add_chunks_same_type(chunk)
        result.append(cur_chunk)
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
        # append Chunk to self
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


class ColorFmt:
    """Wraps given text with escape sequences to apply decoration effects."""

    __slots__ = '_color_codes', '_color_prefix', '_color_suffix'

    _NO_COLOR = None  # dummy ColorFmt object, will be initialized on demand

    def __init__(
        self, color, *, bg_color=None,
        bold=None, faint=None, underline=None, blink=None, crossed=None,
        no_color=False,
        _color_codes_set=None,
    ):
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
        - underline: can have following formats:
          - "STYLE": the STYLE can be one of ['SINGLE', 'DBL', 'CURL', 'DOT', 'DASH']
          - COLOR: format of the COLOR object is the same as format of 'color' arg
          - ("STYLE", COLOR)
          - True: use default style and color
          Default style is "SINGLE", default color is color of the text.
        - other arguments: boolean values, if True the corresponding effect is turned on
        - no_color: if True, all other arguments are ignored and
            created object is 'dummy' - it does not add any effects to text.
        - _color_codes_set: argument for internal use only
        """
        self._color_codes = _color_codes_set or _ColorCodesSet.make(
            color, bg_color, bold, faint, underline, blink, crossed,
            no_color)

        self._color_prefix, self._color_suffix = self._color_codes.make_ansi_sequences()

    @classmethod
    def get_plaintext_fmt(cls) -> 'ColorFmt':
        """Get dummy ColorFmt object (it produces text w/o any effects)."""
        if cls._NO_COLOR is None:
            cls._NO_COLOR = cls(None)
        return cls._NO_COLOR

    def __call__(self, text) -> CHText.Chunk:
        """text -> colored text (CHText object)."""
        return _CHTextChunk(self._color_prefix, text, self._color_suffix)


class ColorBytes:
    """Objects of this class produce bytes with color sequences."""

    __slots__ = '_color_codes', '_color_prefix', '_color_suffix'

    def __init__(
            self, color, *, bg_color=None,
            bold=None, faint=None, underline=None, blink=None, crossed=None,
            no_color=False):
        """Create an object which decorates bytes color sequences.

        Arguments:
            most arguments are self-explained.
            - no_color: if True, all other arguments are ignored and
                created object is 'dummy' - it does not add any effects to text.
        """
        self._color_codes = _ColorCodesSet.make(
            color, bg_color, bold, faint, underline, blink, crossed,
            no_color)

        self._color_prefix, self._color_suffix = self._color_codes.make_ansi_sequences(True)

    def __call__(self, bytes_text):
        return self._color_prefix + bytes_text + self._color_suffix


#########################
# GlobalPalette and ColorsConfig

class _ColorConfColorDescr:
    # Description of a color initialization rules used in ColorsConfig.
    #
    # The initialization rules may be self-sufficient or may refer to another
    # _ColorConfColorDescr object. _ColorConfColorDescr object keeps info about
    # the original description (init_str) and the final ColorFmt object.
    #
    # Format of the init string for _ColorConfColorDescr:
    # - "COLOR/BG_COLOR:modifiers"
    # - "OTHER_SYNTAX:modifiers"
    # - "OTHER_SYNTAX:COLOR/BG_COLOR:modifiers"

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

    _COLORS_NAMES = (
        _ColorCodesSet._COLORS.keys() | {"", "-"} | {f"g{i}" for i in range(24)})

    __slots__ = (
        'synt_id',
        'init_str',
        'fg_color',
        'bg_color',
        'modifiers',
        'parent_syntax_id',
        'src_obj_name',
        'color_fmt',
    )

    def __init__(self, synt_id, init_str, src_obj_descr, no_color=False):
        """Constructor of the _ColorConfColorDescr.

        Arguments:
        - synt_id: id of this syntax item. Example: "TBL.BORDER"
        - init_str: initialization string. Examples:
            "BLUE:bold"
            "TBL.TEXT:RED/BLUE:no_blink"
            (see detailed descr at ColorsConfig constructor doc string)
        - src_obj_descr: description of the object which contains this syntax.
            Usually such an object is Palette class.
        """
        self.synt_id = synt_id
        self.init_str = init_str
        self.src_obj_name = src_obj_descr

        self.color_fmt = None

        (
            self.parent_syntax_id,
            self.fg_color,
            self.bg_color,
            self.modifiers
        ) = self._parse_init_str(init_str)
        if self.fg_color is None:
            self.fg_color = ""
        if self.bg_color is None:
            self.bg_color = ""

        if self.parent_syntax_id is None:
            # color doesn't depend on other ojects, can finish construction now
            self.resolve(None, no_color)
            assert self.color_fmt is not None

    def resolve(self, parent, no_color):
        """Finish initialization: create self.color_fmt obeject.

        It may be not possible to perform this operation in costructor in case this
        color description depends on another color description.

        Arguments:
        - parent: resolved _ColorConfColorDescr object referenced
            by self.parent_syntax_id. (None if there is no parent_syntax_id)
        - no_color: if True use dummy color_fmt which does not add any
            coloring effects to text

        (!) Note that some attributes of self may contain temporary values until
        the object is resolved.
        """
        assert self.color_fmt is None

        if self.parent_syntax_id is not None:
            assert parent is not None
            assert parent.color_fmt is not None  # indicates that parent is resolved

            if self.fg_color == "":
                self.fg_color = parent.fg_color
            if self.bg_color == "":
                self.bg_color = parent.bg_color
            self.modifiers = {**parent.modifiers, **self.modifiers}
        else:
            assert parent is None
            if self.fg_color in ["-", ""]:
                self.fg_color = None
            if self.bg_color in ["-", ""]:
                self.bg_color = None

        if no_color:
            self.color_fmt = ColorsConfig._NO_EFFECTS_FMT
        else:
            self.color_fmt = ColorFmt(
                self.fg_color, bg_color=self.bg_color, **self.modifiers)

    @classmethod
    def _parse_init_str(cls, init_str):
        # parse string description of a color
        # color_descr_srt -> (parent_syntax_id, fg_color, bg_color, modifiers)
        #
        # The init_str may contain up to 3 sections and may look like:
        #
        # "PARENT_SYNTAX:NEW_COLOR/NEW_BG_COLOR:bold,no_crossed"
        #
        # All the sections are optional, so the parsing process is somewhat complicated
        fg_color = None
        bg_color = None
        parent_syntax_id = None

        chunks = init_str.split(':')
        if len(chunks) > 3:
            raise ValueError(
                f"invalid color description: '{init_str}'. "
                f"It contains {len(chunks)} sections, maximum is 3")

        result_parent_syntax_id = None
        processed_fg_bg_colors_section = None
        result_fg_color = None
        result_bg_color = None
        processed_modifiers_section = None
        result_modifiers = None

        for color_section in chunks:
            color_section = color_section.strip()

            if color_section == "":
                # to find out the type of the empty section we have to check what sections
                # had been processed already
                if result_parent_syntax_id is None:
                    result_parent_syntax_id = ""
                elif processed_fg_bg_colors_section is None:
                    processed_fg_bg_colors_section = ""
                    result_fg_color = ""
                    result_bg_color = ""
                elif processed_modifiers_section is None:
                    processed_modifiers_section = ""
                    result_modifiers = {}
                continue

            parent_syntax_id, fg_color, bg_color = cls._parse_colors_part(
                color_section, init_str)

            if parent_syntax_id is not None:
                # the parsed section contains the name of parent syntax
                assert fg_color is None and bg_color is None
                if result_parent_syntax_id is not None:
                    raise ValueError(
                        f"invalid color description: '{init_str}'. "
                        f"It contains two sections which look like parent syntax id: "
                        f"{result_parent_syntax_id} and {parent_syntax_id}")
                result_parent_syntax_id = parent_syntax_id
                continue

            if fg_color is not None or bg_color is not None:
                # the parsed section contains foreground/background colors
                assert fg_color is not None and bg_color is not None
                if result_fg_color is not None:
                    raise ValueError(
                        f"invalid color description: '{init_str}'. "
                        f"It contains two sections corresponding to foreground/background "
                        f"colors: '{processed_fg_bg_colors_section}' and '{color_section}'")
                result_fg_color = fg_color
                result_bg_color = bg_color
                processed_fg_bg_colors_section = color_section
                continue

            # it must be a section with modifiers
            if result_modifiers is not None:
                raise ValueError(
                    f"invalid color description: '{init_str}'. "
                    f"It contains two sections corresponding to format modifiers "
                    f"colors: '{processed_modifiers_section}' and '{color_section}'")
            result_modifiers = cls._parse_modifiers(color_section, init_str)

        if result_modifiers is None:
            result_modifiers = {}

        if result_fg_color is None:
            result_fg_color = ""
        if result_bg_color is None:
            result_bg_color = ""

        return result_parent_syntax_id, result_fg_color, result_bg_color, result_modifiers

    @classmethod
    def _parse_colors_part(cls, colors_section, orig_init_str):
        # part of _parse_init_str operation.
        #
        # Analizes a single section of the color init string
        # and returns (parent, fg_color, bg_color)
        #
        # All three elements of the returned tuple are None if the section does not
        # corresponds to "OTHER_SYNTAX" or "foreground/background colors" part of the
        # color init sting.
        #
        # Examples of the section:
        #
        # "OTHER_SYNTAX"
        # "BLUE"
        # "BLUE/YELLOW"
        # "107"             <- int id of the color
        # "(2,3,4)/108"     <- fg_color in rgb format, bg_color - int
        # "g4"              <- shade of grey
        chunks = colors_section.split('/')
        if len(chunks) > 2:
            raise ValueError(
                f"invalid colors description part '{colors_section}'. "
                f"Full color description: '{orig_init_str}'")

        if len(chunks) == 2:
            # it must be "COLOR/BG_COLOR"
            fg_color, bg_color = [cls._parse_color(c, orig_init_str) for c in chunks]
            return None, fg_color, bg_color

        # it may be either COLOR or OTHER_SYNTAX_NAME or modifiers
        # 1. check if it is modifiers
        if cls._is_modifiers_section(colors_section):
            return None, None, None

        # 2. check if it is COLOR
        try:
            fg_color = cls._parse_color(colors_section, orig_init_str)
            return None, fg_color, ""  # "" - means default color
        except ValueError:
            pass

        # 3. have to interprete it as OTHER_SYNTAX_NAME
        return colors_section, None, None

    @classmethod
    def _is_modifiers_section(cls, colors_section) -> bool:
        # check if the color decription section looks like a section containing
        # format modifiers
        if '=' in colors_section:
            return True
        if colors_section in cls._MODIFIERS:
            return True
        if ',' in colors_section:
            opts_names = {x.split('=')[0] for x in colors_section.split(',')}
            if any(opt_name in cls._MODIFIERS for opt_name in opts_names):
                return True
        return False

    @classmethod
    def _parse_color(cls, color, orig_init_str):
        # part of _parse_init_str operation.
        #
        # Parses the string description of a single color and return corresponding
        # object.
        #
        # Examples:
        #   "BLUE" -> "BLUE"
        #   "235" -> 235
        #   "(3,4,5)" -> (3,4,5)
        #   "g4" -> "g4"
        try:
            return cls._parse_color_impl(color)
        except ValueError as err:
            problem_descr = str(err)
            if problem_descr:
                problem_descr = f" {problem_descr}"

        raise ValueError(
            f"color description '{orig_init_str}' contains incorrect "
            f"color identifier '{color}'.{problem_descr}")

    @classmethod
    def _parse_color_impl(cls, color):
        # part of _parse_init_str operation.
        # do all the job for _parse_color method
        color = color.strip()

        if color in cls._COLORS_NAMES:
            return color

        if color.startswith('('):
            # it must be an (r, g, b) tuple
            if not color.endswith(')'):
                raise ValueError("")
            color = color[1:-1]
            chunks = [c.strip() for c in color.split(",")]
            if len(chunks) != 3:
                raise ValueError("Color tuple must contain 3 elements")
            r, g, b = [int(c) for c in chunks]
            if any(x < 0 or x > 5 for x in (r, g, b)):
                raise ValueError(
                    "all values in (r, g, b) tuple must be in range [1-5]")
            return (r, g, b)

        # check if it is an integer color code
        color_int_id = None
        try:
            color_int_id = int(color)
        except ValueError:
            pass

        if color_int_id is not None:
            if color_int_id < 0 or color_int_id > 255:
                raise ValueError(
                    f"int color value {color_int_id} should be in range [0-255]")
            return color_int_id

        # it's not a color. Probably it's the OTHER_SYNTAX_NAME
        raise ValueError(f"'{color}' is not a valid color identifier")

    @classmethod
    def _parse_modifiers(cls, modifiers_str, color_descr):
        # part of _parse_init_str operation.
        #
        # "bold,no_blink,underline=CURL(5,1,0)"
        #    -> {"bold": True, "blink": False, "underline": "CURL(5,1,0)"}
        #
        # Most of the midifiers are simple: one can turned on, off or not present.
        # But the 'underline' modifier can contain some some additional options

        # can not just split by ',' because 'underline' option can contain ','
        chunks = [s.strip() for s in cls._split_modifiers_section(modifiers_str)]

        chunks = [s for s in chunks if s]
        modifiers = {}
        for modifier in chunks:
            if '=' in modifier:
                modifier, value = modifier.split('=', maxsplit=1)
                if modifier not in cls._MODIFIERS:
                    raise ValueError(
                        f"invalid color description: '{color_descr}': "
                        f"invalid color modifier name '{modifier}'.")
                if modifier == 'underline':
                    modifiers[modifier] = cls._parse_underline_modifier(value)
                else:
                    raise ValueError(
                        f"invalid color description: '{color_descr}': "
                        f"parameters can not be explicitely specified for "
                        f"color modifier '{modifier}'.")
            else:
                try:
                    mod_name, mod_value = cls._MODIFIERS[modifier]
                except KeyError:
                    raise ValueError(
                        f"invalid color description: '{color_descr}': "
                        f"invalid color modifier name '{modifier}'.")
                modifiers[mod_name] = mod_value

        return modifiers

    @classmethod
    def _split_modifiers_section(cls, modifiers_section):
        # split the modifiers part of the color description string
        # The string consists of several comma-delimited parts, the problem is
        # that some parts may also contain commas.
        result = []
        cur_chunk_start_pos = 0
        inside_parenths = False
        for cur_pos in range(len(modifiers_section)):
            cur_char = modifiers_section[cur_pos]
            if inside_parenths:
                if cur_char == ')':
                    inside_parenths = False
                continue
            if cur_char == '(':
                inside_parenths = True
                continue

            if cur_char == ',':
                result.append(modifiers_section[cur_chunk_start_pos:cur_pos])
                cur_chunk_start_pos = cur_pos + 1

        cur_pos = len(modifiers_section)
        if cur_pos > cur_chunk_start_pos:
            result.append(modifiers_section[cur_chunk_start_pos:cur_pos])

        return result

    @classmethod
    def _parse_underline_modifier(cls, option_value):
        # convert string value of 'underline' option to the form expected
        # by ColorFmt constructor.
        #
        # General form of the input string value is:
        # - "STYLE(COLOR)"
        # where all the parts are optional and parentheses are required only
        # if STYLE is specified or the GOLOR is (r, g, b) tuple.

        # The value may be of different formats:
        # - "COLOR"
        # - "STYLE"
        # - "STYLE(r,g,b)"
        # - "STYLE(256colorid)"

        value = option_value.strip()
        if '(' in value:
            if value[-1] != ')':
                raise ValueError(
                    f"Invalid value of 'underline' option: '{option_value}'. "
                    f"Closing ')' either not found or is not the last char.")
            uline_style, inner_color_part = value[:-1].split('(', maxsplit=1)
            inner_color_part = inner_color_part.strip()
            color_arg = (
                cls._detect_rgb_tuple(inner_color_part, option_value)
                or cls._detect_int_code(inner_color_part)
                or inner_color_part)

            if uline_style == "":
                return color_arg

            return (uline_style, color_arg)

        # '(' not found, so there is no 'STYLE' part
        color_arg = cls._detect_int_code(value) or value

        return color_arg

    @classmethod
    def _detect_rgb_tuple(cls, rgb_str, orig_option_value):
        # "r,g,b" -> (r, g, b)
        # Returns None if the arg does not look like an "r,g,b" tuple
        # ot raises error if it does look like an "r,g,b" but has some problems
        if ',' in rgb_str:
            # "r,g,b" -> (r, g, b)
            try:
                rgb = tuple(int(x.strip()) for x in rgb_str.split(','))
                return rgb
            except ValueError:
                raise ValueError(
                    f"Invalid value of 'underline' option: '{orig_option_value}'. "
                    f"All the items of the '(r,g,b)' section should be integers.")
        return None

    @classmethod
    def _detect_int_code(cls, color_str):
        # 'color_part' -> int or None
        try:
            color_code = int(color_str)
            return color_code
        except ValueError:
            pass

        return None


class ColorsConfig:
    """Colors configuration. Usually a global object.

    ColorsConfig contains colors for miscelaneous syntax items such as
    numbers in pretty-printed jsons or table borders.

    ColorsConfig contains a mapping: glob_synt_id -> ColorFmt
    (example: "TABLE.BORDER" -> ColorFmt("GREEN"))

    Miscellaneous application components may register the defult values for the syntax
    id's they are going to use. The config may be initilised with data for all the
    syntax ids used by all the components of the application (for example it may be
    read from a conf file), but this is not required. Application components will
    add all the required missing syntax ids at runtime.

    It is possible to get a report of what colors are used for different syntax
    groups and then use this report as a starting point for colors configuration
    in the application config file.

    Standard users of the ColorsConfig are Palette classes and objects.

    Use ak.color.get_global_colors_config() to get information about current state
    of the global ColorsConf.
    """

    _NO_EFFECTS_FMT = ColorFmt.get_plaintext_fmt()

    DFLT_SYNTAX_ID = "TEXT"
    BUILT_IN_CONFIG = {
        "TEXT": "",  # supposed to be used as default text settings
        "NAME": "GREEN:bold",
        "KEYWORD": "BLUE:bold",
        "NUMBER": "YELLOW",
        "OK": "GREEN:bold",
        "WARN": "RED",
        "ERROR": "RED:bold",
    }

    __slots__ = (
        'syntax_map',
        'registered_sources',
        'no_color',
        '_cache',
    )

    def __init__(self, init_config=None, *, no_color=False):
        """Constructor.

        Arguments:
        - init_config: colors config (*)
        - no_color: if True - ignores all other config settings and creates
          'no-color' config

        (*) data for the colors config is expected to be read from the config file.
        Example of colors config:
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
            "OTHER_SYNTAX:modifiers"
            "OTHER_SYNTAX:COLOR/BG_COLOR:modifiers"

        here:
        - modifiers is a list of individual modifiers with optional 'no_' prefix
        - COLOR and BG_COLOR:
            - color identifiers as described in ColorFmt constructor:
                - name of the color
                - a number
                - r,g,b tuple
                - string in form 'g0' - 'g23'
            - "-" - indicator that the system color should be used
            - "" (empty string) - indicator that the "default" color should be used.
                The default color is the color of the "OTHER_SYNTAX" in case it
                is used in the description, or the system color otherwise

        Examples:
            "YELLOW/BLUE:bold,faint,underline,blink,crossed"
            "GREEN"
            "RED:bold"
            "OTHER_SYNTAX_NAME:no_bold"

        Use colors_config.make_report() method to get more information about
        names of syntax items currently used in the application and
        corresponding colors.
        """
        if init_config is None:
            init_config = {}
        self.no_color = no_color

        self._cache = {}  # place for palette classes to keep palette objects
                          # created using this config. The ColorsConfig does not care
                          # what other components keep in this cache, it's only
                          # responsible to clear the cache if config changes
        self.registered_sources = set()
        self.syntax_map = {}

        new_init_items = self._flatten_dict(init_config)
        self.add_new_items(new_init_items, "config")

        new_init_items = self._flatten_dict(self.BUILT_IN_CONFIG)
        self.add_new_items(new_init_items, "built in")

    def add_new_items(self, new_items, src_obj_descr):
        """Register information about new syntaxes.

        When some component wants to use the ColorsConfig but the config
        does not contain information about the syntaxes this component requires
        the component registeres desired syntaxes in the config.

        Arguments:
        - new_items: {synt_id: init_str}, where init_str contains description
            of the color, corresponding to the syntax
        - src_obj_descr: description of the object which adds these items to config.
            Will be used for reporting purposes.
        """
        assert isinstance(src_obj_descr, str)

        if not new_items:
            return

        any_modifications = False

        if any(synt_id not in self.syntax_map for synt_id in new_items):
            self._cache = {}

        for synt_id, init_str in new_items.items():
            if synt_id in self.syntax_map:
                # properties of this syntax are defined already. Probably in
                # config file.
                continue
            self.syntax_map[synt_id] = _ColorConfColorDescr(
                synt_id, init_str, src_obj_descr, self.no_color)
            any_modifications = True

        # Information about new syntax items has been registered
        # But construction of some syntax items may be not finished yet (items
        # may depend on other items, implementing rules such as 'TABLE.BORDER is
        # same as NUMBER, but bold and blinking')
        # Both new items and previously registered items may be not fully
        # constructed yet. For example, the above-mentioned rule could be
        # present in the initial config, but it can't be resolved util information
        # about NUMBER syntax is available.
        #
        # Finish construction (resolve) those items we have enough information for.

        to_resolve = {
            synt_id: syntax_color
            for synt_id, syntax_color in self.syntax_map.items()
            if syntax_color.color_fmt is None
        }

        # id's of _ColorConfColorDescr items which can't be resolved for now
        cant_resolve = set()

        while to_resolve:
            new_resolved = set()
            for synt_id, syntax_color in sorted(to_resolve.items()):
                if syntax_color.color_fmt is not None:
                    continue
                path = []
                while True:
                    if syntax_color.synt_id in path:
                        assert False, f"circular dependency detected. Fix me."
                    if syntax_color.color_fmt is not None:
                        # all the syntaxes accumulated in path may be resolved now
                        parent_syntax_color = syntax_color
                        for synt_id in reversed(path):
                            syntax_color = self.syntax_map[synt_id]
                            syntax_color.resolve(
                                parent_syntax_color, self.no_color)
                            new_resolved.add(syntax_color.synt_id)
                            parent_syntax_color = syntax_color
                        break
                    if (
                        syntax_color.synt_id in cant_resolve
                        or syntax_color.parent_syntax_id not in self.syntax_map
                    ):
                        # all the syntaxes accumulated in path can't be resolved now
                        cant_resolve.update(path)
                        break
                    path.append(syntax_color.synt_id)
                    syntax_color = self.syntax_map[syntax_color.parent_syntax_id]
            if new_resolved:
                any_modifications = True
            else:
                # no more items can be resolved
                break

        if any_modifications and self is _GLOBAL_COLORS_CONF:
            # self is the global config, so it is necessary to update all the
            # synced palette objects
            set_global_colors_config(self)

    def put_into_cache(self, cache_key, the_obj):
        """Put some object to the ColorsConfig cache.

        Arguments:
        - cache_key: usually Palette class
        - the_obj: usually the corresponding palette object

        ColorsConfig does not care what objects are stored in the cache.
        Responsibility of the ColorsConfig is to reset the cache if the config's
        data is updated.
        """
        self._cache[cache_key] = the_obj

    def get_cached_obj(self, cache_key):
        """Get object from ColorsConfig cache.

        See 'put_into_cache' for more detailed description.
        """
        return self._cache.get(cache_key)

    @classmethod
    def _flatten_dict(cls, syntax_map):
        # transform structure of nested dictionaries into a flat dictionary.
        # keys of items corresponding to elements of nested disctionaris are
        # composed of names of items in path:
        # {'TABLE': {'BORDER': value}}  ->  {'TABLE.BORDER': value}
        result = {}
        for key, value in syntax_map.items():
            if isinstance(value, str):
                result[key] = value
            elif isinstance(value, dict):
                flatten_subdict = cls._flatten_dict(value)
                for skey, val_and_src in flatten_subdict.items():
                    result[f"{key}.{skey}"] = val_and_src
        return result

    def get_color(self, conf_synt_id) -> ColorFmt:
        """syntax name -> ColorFmt"""
        syntax_color = self.syntax_map.get(conf_synt_id)
        if syntax_color is None:
            syntax_color = self.syntax_map.get(self.DFLT_SYNTAX_ID)
        if syntax_color is None or syntax_color.color_fmt is None:
            return self._NO_EFFECTS_FMT
        return syntax_color.color_fmt

    def get_palette(self) -> 'GlobalPalette':
        """Get Palette which contains all the syntaxes in this ColorsConfig."""
        return GlobalPalette(colors_conf=self)

    def color_conf_component_is_registered(self, src_obj) -> bool:
        """Check if Palette object is registered in the ColorsConfig"""
        return src_obj in self.registered_sources

    def register_color_conf_component(self, syntax_map, src_obj):
        """Register Palette object in the ColorsConfig"""
        assert src_obj not in self.registered_sources, f"{src_obj=}"
        self.registered_sources.add(src_obj)
        new_items_flat_init_conf = self._flatten_dict(syntax_map)
        self.add_new_items(new_items_flat_init_conf, str(src_obj))

    def make_report(self) -> str:
        """Create colored report of self."""
        return "\n".join(self.gen_report_lines())

    def gen_report_lines(self) -> Iterator[str]:
        """Generate lines for self-report"""
        offset_step = "  "
        rep_lines = []  # ["name and init_str", "status", "source"]
        common_path = []  # path to a current syntax element
        for syntax_name, syntax_color in sorted(self.syntax_map.items()):
            syntax_descr = syntax_color.init_str
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
                rep_lines.append((f"{offset_step*depth}{group_name} ->", None, None))

            assert len(cur_path) == len(common_path)
            # report the syntax description
            depth = len(common_path)
            prefix = self._NO_EFFECTS_FMT(offset_step*depth)
            color_fmt = syntax_color.color_fmt
            status = None
            if color_fmt is None:
                # this syntax color is not resolved.
                color_fmt = self._NO_EFFECTS_FMT
                status = "<NOT RESOLVED>"
            rep_lines.append(
                (
                    prefix + f"{cur_name}: " + color_fmt(syntax_descr),
                    status,
                    syntax_color.src_obj_name,
                ))
        # raw information is ready, yield the report lines
        show_status = any(l[1] is not None for l in rep_lines)
        max_main_part_width = max(len(l[0]) for l in rep_lines)
        main_part_width = min(150, max(40, max_main_part_width))
        for line in rep_lines:
            if line[2] is None:
                # this is a technical line, showes group name
                yield line[0]
                continue
            # this line contains info about some syntax color
            colored_text = line[0].fixed_len(main_part_width)

            # add info about the status
            if show_status:
                status = line[1] if line[1] is not None else "<OK>"
                colored_text += f" !{status:15}"

            # add info about the source
            colored_text += f" <- {line[2]}"

            yield str(colored_text)


class ConfColor:
    """Indicator of the color item to be used in Palette classes declarations."""
    def __init__(self, plt_synt_id):
        self.plt_synt_id = plt_synt_id

    def __call__(self, text) -> CHText.Chunk:
        """Just a trick to persuade IDE that an item is a callable.

        It will be a callable after processing by _PaletteMeta.
        """
        assert False


class _PaletteMeta(type):
    # Meta class for Palette-derived classes.
    #
    # Palette-derived classes have two important features:
    # 1. Constructor of Palette does not create a new palette object if the palette
    #   of this class was already created using the given config
    # 2. Substitutes ConfColor items in class declaration with callables which
    #   return corresponding ColorFmt objects.
    def __call__(
        palette_class, no_color=False, colors_conf=None,
        _local_colors=None, *, synced=False,
    ):
        """Intercept construction of the Palette object.

        Does not create a new object of palette_class if matching object already
        exists in colors_conf cache.
        """
        assert _local_colors is None, (
            f"Error calling constructor of {palette_class}. _local_colors "
            f"argument must not be specified explicitely.")
        if synced:
            assert colors_conf is None, (
                f"Error calling constructor of {palette_class}. colors_conf "
                f"argument must not be specified because synced=True and the "
                f"palette will be constructed and always synced with the global "
                f"colors config.")

        if synced:
            existing_synced_palette = _GSYNCED_PALETTES.get(palette_class)
            if existing_synced_palette is not None:
                return existing_synced_palette

        if colors_conf is None:
            colors_conf = get_global_colors_config()

        if not synced:
            existing_palette = palette_class._get_existing_palette(
                colors_conf, no_color)
            if existing_palette is not None:
                return existing_palette

        _local_colors = palette_class._prepare_local_colors(colors_conf, no_color)

        # there is no existing palette of this class. Need to create a new one
        palette = palette_class.__new__(
            palette_class, colors_conf, no_color, _local_colors, synced=synced)
        palette_class.__init__(
            palette, colors_conf, no_color, _local_colors, synced=synced)

        if synced:
            palette = _GSYNCED_PALETTES.setdefault(palette_class, palette)
        else:
            palette_class._store_palette_in_cache(palette, colors_conf, no_color)

        return palette

    def __new__(meta, classname, supers, classdict):
        # _LOCAL_SYNTAX - {plt_synt_id: syntax_id_in_colors_conf}
        # contents of this dictionary is created based on 'ConfColor' items in
        # the classdict.
        for attr in ['_LOCAL_SYNTAX', '_PALETTE_NO_COLOR']:
            assert attr not in classdict, (
                f"Error in {classname} class declaration. '{attr}' must not "
                f"be declared explicitly")

        local_syntax_map = {}
        # In order to implement inheritance it is necessary to combine this data
        # from base classes and current class
        for base_class in supers:
            base_syntax_map = getattr(base_class, '_LOCAL_SYNTAX')
            if base_syntax_map is not None:
                local_syntax_map.update(base_syntax_map)

        for name, field in classdict.items():
            if isinstance(field, ConfColor):
                local_syntax_map[name] = field.plt_synt_id

        classdict = {n: v for n, v in classdict.items() if n not in local_syntax_map}
        classdict['_LOCAL_SYNTAX'] = local_syntax_map
        classdict['_PALETTE_NO_COLOR'] = None

        return type.__new__(meta, classname, supers, classdict)


class Palette(metaclass=_PaletteMeta):
    """Collection of color formatters to be used by some application component.

    Any application component may create it's own Palette class, which contains
    information about syntax names and color colors corresponding to these synatxes.

    Example:

    class EnumPalette(Palette):

        # These syntax names will be incorporated into the global colors config.
        # Default colors are specified here, these colors may be overridden
        # during ColorsConfig constraction.
        SYNTAX_DEFAULTS = {
            "ENUM.ID": "GREEN:bold",
            "ENUM.NAME": "KEYWORD",

            "CONNOTATION.WARN": "underline=DBL(RED)
        }

        # Declarations of the formatters present in this Palette
        enum_id_color = ConfColor("ENUM.ID")
        name = ConfColor("ENUM.NAME")

        # connotations are usual formatters
        warn_conn = ConfColor("CONNOTATION.WARN")

    ...

    cp = EnumPalette()
    cp1 = EnumPalette()  # cp is cp1

    You can use the following ways to produce decorated text:

    1. directly using formatters declared in the palette:
    cp.enum_id_color("42")     # produces CHText object representing green bold "42"

    2. combine formatters and use the result fomatter:
    fmt = cp.get_color('name', 'warn_conn')  # produces ColorFmt obj which decorated text
                                             # using a combination of effects defined in
                                             # 'name' and 'warn_conn' formatters
    fmt("Arnold")   # produces CHText object representing "Arnold" text same way
                    # as "KEYWORD" but using double line red underline

    """
    # List of other Palette classes this one depends on (uses syntaxes defined
    # in that classes)
    PARENT_PALETTES = None

    # init rules of the new global syntaxes introduced by this class
    SYNTAX_DEFAULTS = None  # {synt_id: default_color}

    # default syntax ID which is used for usual text not corresponding to any
    # syntax id.
    text = ConfColor(ColorsConfig.DFLT_SYNTAX_ID)

    def __init__(self, colors_conf=None, no_color=False, _local_colors=None, synced=False):
        """Constructor of Palette.

        Arguments:
        - colors_conf: ColorsConfig object. By default the global colors
            config is used.
        - no_color: if True creates a palette object which produces text without
            any coloring effects.
        - _local_colors: must never be specified explicitely (*).
        - synced: if the palette is synced with the colors_config. When a new palette
            class gets registered in config the config may change. synced palettes will
            be modified accordingly.

        (*) Palette's meta-class intercepts the constructor call and prepares
        arguments for the constructor. When the constructor is actually called
        all it's arguments are specified.
        """
        # pylint: disable=unused-argument
        assert self._LOCAL_SYNTAX.keys() == _local_colors.keys()

        self._synced = synced
        self._local_colors = _local_colors  # {plt_synt_id: (color_conf_id, ColorFmt)}
        self._color_fmts = {}  # {(plt_synt_id, (connotation, ...)): ColorFmt}

        for n, v in self._local_colors.items():
            setattr(self, n, v[1])

    @classmethod
    def _get_existing_palette(cls, colors_conf, no_color):
        # return cached palette object if one exists
        # location of the cached palette depends on 'no_color' argument
        if no_color:
            # in this case palette does not actually depend on config. So
            # the cached object is stored in the class.
            # Still let's register the Palette class in config so that the
            # syntaxes used in Palette be reported in the config
            cls.register_in_colors_conf(colors_conf)
            return cls._PALETTE_NO_COLOR
        else:
            # colored palette may be cached in the config
            return colors_conf.get_cached_obj(cls)

    @classmethod
    def _prepare_local_colors(cls, colors_conf, no_color):
        # prepare the '_local_colors' argument for the Palette constructor
        if no_color:
            return {
                accessor_name: (synt_id, ColorsConfig._NO_EFFECTS_FMT)
                for accessor_name, synt_id in cls._LOCAL_SYNTAX.items()
            }
        else:
            cls.register_in_colors_conf(colors_conf)
            return {
                accessor_name: (synt_id, colors_conf.get_color(synt_id))
                for accessor_name, synt_id in cls._LOCAL_SYNTAX.items()
            }

    @classmethod
    def _store_palette_in_cache(cls, palette, colors_conf, no_color):
        # store newly created palette object in cache. Location of cache
        # depends on type of palette.
        if no_color:
            cls._PALETTE_NO_COLOR = palette
        else:
            colors_conf.put_into_cache(cls, palette)

    def get_color(self, plt_synt_id, *connotations) -> ColorFmt:
        """Get ColorFmt stored in the palette.

        Argument:
        - plt_synt_id: syntax id as specified in Palette class declaration:
            plt_synt_id = ConfColor(...)
        - connotations: syntax ids to be used as connotations.
        """
        key = (plt_synt_id, connotations)
        color_fmt = self._color_fmts.get(key)
        if color_fmt is None:
            color_fmt = self._construct_color_fmt(plt_synt_id, connotations)
            self._color_fmts[key] = color_fmt

        return color_fmt

    def _construct_color_fmt(self, plt_synt_id, connotations):
        # combine the ColorFmt objects corresponding to plt_synt_id and connotations
        # into a single ColorFmt

        main_fmt = self._get_plt_synt_formater(plt_synt_id)

        if len(connotations) == 0:
            return main_fmt

        fmts = [main_fmt, ]

        for conn in connotations:
            fmts.append(self._get_plt_synt_formater(conn))

        color_codes_set = _ColorCodesSet.combine_color_code_sets(
            fmt._color_codes for fmt in fmts)

        return ColorFmt(None, _color_codes_set=color_codes_set)

    def _get_plt_synt_formater(self, plt_synt_id) -> ColorFmt:
        # plt_synt_id -> ColorFmt
        x = self._local_colors.get(plt_synt_id)
        if x is None:
            return self.text  # dummy plain-text formatter
        return x[1]

    def _sync_with_config(self, colors_conf):
        # update self after the state of the global config has changed
        assert self._synced
        self._color_fmts = {}
        self.register_in_colors_conf(colors_conf)
        for accessor_name, conf_synt_id in self._LOCAL_SYNTAX.items():
            setattr(self, accessor_name, colors_conf.get_color(conf_synt_id))

    @classmethod
    def register_in_colors_conf(cls, colors_conf):
        """Register Palette class in the Colors Config.

        Registration process merges syntaxes declared in cls.SYNTAX_DEFAULTS to
        the config. Thus Colors Config Report reports all the syntaxes/colors
        used in the system, even if some of these syntaxes are not configued
        in the config explicitely.
        """
        if colors_conf.color_conf_component_is_registered(cls):
            return

        if cls.PARENT_PALETTES is not None:
            for p_cls in cls.PARENT_PALETTES:
                p_cls.register_in_colors_conf(colors_conf)

        if cls.SYNTAX_DEFAULTS is not None:
            colors_conf.register_color_conf_component(cls.SYNTAX_DEFAULTS, cls)

    def make_report(self) -> str:
        """Create colored report of self."""
        return "\n".join(
            f"{plt_synt_id}: {CHText(color_fmt(syntax_conf))}"
            for plt_synt_id, (syntax_conf, color_fmt)
            in sorted(self._local_colors.items())
        )


class CompoundPalette(Palette):
    """Extension of the Palette class to be used in more complex cases.

    An example is palette required to print a table. The palette may contain
    colors for table border, table title, etc. But the table may contain enum
    values - which uses it's own palette.

    In order to create a palette which customizes colors of the table and colors of
    the enum values in this table one should derive a new class from TablePalette
    class. The following example is artificial:

    class CustomizedTablePalette(TablePalette):
        border = ConfColor("RED")  # overrides table border color

        SUB_PALETTES_MAP = {
            (EnumPalette, "shade"): CustomizedEnumPaletteClass
        }

    table_object.ch_text(palette=CustomizedTablePalette)

    Note, that Table class does not know about enums and it's palettes.
    When the table produces the text for a cell it sees that the the cell
    uses EnumPalette class by default. But instead of EnumPalette class the
    CustomizedEnumPaletteClass will be used because of SUB_PALETTES_MAP
    configuration.

    The second element of the key in SUB_PALETTES_MAP can be used if the enums
    may appear in different parts of the table and we want to customize these
    cells differently. Interpretation the "shade" item is done by the class
    which uses the palette, actual Table class does not uses it and expects
    this element to be None).
    """
    SUB_PALETTES_MAP = None  # {(Palette, "modifier name"): AltLocalPalette}

    def __init__(
        self, colors_conf=None, no_color=False, _local_colors=None,
        synced=False,
    ):
        assert not synced, "synced CompoundPalette are not supported"
        super().__init__(colors_conf, no_color, _local_colors, synced=synced)
        self._no_color = no_color
        self.colors_conf = colors_conf
        self._sub_palettes = {}

    def get_sub_palette(
        self, palette_class, shade_name=None
    ):
        key = (palette_class, shade_name)
        result = self._sub_palettes.get(key)
        if result is None:
            actual_palette_class = self.SUB_PALETTES_MAP.get(
                key, palette_class)
            result = actual_palette_class(self._no_color, self.colors_conf)
            self._sub_palettes[key] = result
        return result


class GlobalPalette(Palette):
    """Object of this class provides access to all the colors in the global config.

    ak.color module contains a synced instance of this class, so that it
    is possible to

        import ak.color.global_palette as gp

    even before colors are configured. The imported 'gp' object would provide
    access to the current global config.

    There are two ways to get color formatters:

        gp["TABLE.BORDER"]     # returns ColorFmt corresponging to "TABLE.BORDER"
                               # element in the config
        gp.keyword             # same as gp["KEYWORD"], shortcat for standard
                               # syntaxes
    """

    # access to standard syntaxes
    text = ConfColor("TEXT")
    name = ConfColor("NAME")
    keyword = ConfColor("KEYWORD")
    ok = ConfColor("OK")
    warn = ConfColor("WARN")
    error = ConfColor("ERROR")

    def __init__(
        self, colors_conf=None, no_color=None, _local_colors=None, synced=False
    ):
        """Constructor of GlobalPalette.

        Arguments are the same as arguments of Palette.
        """
        super().__init__(colors_conf, no_color, _local_colors, synced=synced)
        self._colors_conf = colors_conf

    def get_color(self, plt_synt_id) -> ColorFmt:
        """plt_synt_id -> ColorFmt"""
        return self._colors_conf.get_color(plt_synt_id)

    def __getitem__(self, index):
        """same behavior as get_color method"""
        return self.get_color(index)

    def _sync_with_config(self, colors_conf):
        """Update the global palette after the global colors config has changed."""
        self._colors_conf = colors_conf
        super()._sync_with_config(colors_conf)


class PaletteUser:
    """Mixin which implememts a helper method which constructs palette object.

    Usage of this mixin is optional.
    """

    PALETTE_CLASS = None

    @classmethod
    def _mk_palette(cls, palette, no_color, compound_palette, shade_name):
        # methods which produce colored text should accept four optional
        # agruments which control the colors of the result:
        # - palette: either Palette-derived class or an object of such class
        # - no_color: instructs to produce text without color effects,
        #     False by default
        # - compound_palette: optional CompoundPalette object which contains
        #     palette for cls as a sub-palette
        # - shade_name: optional identifier of the "shade" of required palette in the
        #     compound_palette
        #
        # This method provides standard way to create a palette object from
        # these arguments.

        if compound_palette is not None:
            assert palette is None, (
                f"both 'palette' and 'compound_palette' arguments are specified")
            assert cls.PALETTE_CLASS is not None, (
                f"'PALETTE_CLASS' is not implemented in {str(cls)}")
            return compound_palette.get_sub_palette(cls.PALETTE_CLASS, shade_name)
        else:
            assert shade_name is None, (
                f"{shade_name=} argument is specified, "
                f"but 'compound_palette' is None")

        if palette is not None:
            if isinstance(palette, Palette):
                # ready-to-use palette object is provided
                if no_color:
                    palette = type(palette)(no_color=True)
                return palette
            else:
                assert isinstance(palette, type), (
                    f"unexpected {palette=} argument. Expected either "
                    f"Palette-derived class or an object of such class")

        assert cls.PALETTE_CLASS is not None, (
            f"'PALETTE_CLASS' is not implemented in {str(cls)}")

        palette_class = palette or cls.PALETTE_CLASS

        return palette_class(no_color)

    def make_palette(
        self, *, palette=None, no_color=False,
        compound_palette=None, shade_name=None,
    ):
        return self._mk_palette(palette, no_color, compound_palette, shade_name)


def get_global_colors_config():
    """Get global ColorsConfig.

    You may want to get the colors config to prepare a report of syntaxes and
    corresponding colors used in the program:

        print(get_global_colors_config().make_report())
    """
    global _GLOBAL_COLORS_CONF
    if _GLOBAL_COLORS_CONF is None:
        _GLOBAL_COLORS_CONF = ColorsConfig()
    return _GLOBAL_COLORS_CONF


def set_global_colors_config(colors_config):
    """Set global ColorsConfig"""
    global _GLOBAL_COLORS_CONF
    if colors_config is None:
        colors_config = ColorsConfig()
    _GLOBAL_COLORS_CONF = colors_config

    for palette in _GSYNCED_PALETTES.values():
        palette._sync_with_config(colors_config)


_GLOBAL_COLORS_CONF = None
_GSYNCED_PALETTES = {}


# global_palette is a synced palette object which provides color formatters bases
# on a current state of the global config
global_palette = GlobalPalette(synced=True)
