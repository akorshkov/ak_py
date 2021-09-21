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
    t_no_color = t.no_color()

    # print color examples table: each cell have different color/effects
    print(make_examples('text'))
"""


#########################
# Color printer

class ColoredText:
    """Colored text. Consists of several mono-colored parts."""

    class _ColoredChunk:
        # Chunk of ColoredText which has same color.
        __slots__ = 'c_prefix', 'text', 'c_suffix'
        def __init__(self, prefix, text, suffix):
            self.c_prefix = prefix
            self.text = text
            self.c_suffix = suffix

        def _equal(self, other):
            return (
                self.c_prefix == other.c_prefix
                and self.text == other.text
                and self.c_suffix == other.c_suffix)

        def _clone(self):
            return type(self)(self.c_prefix, self.text, self.c_suffix)

    def __init__(self, *parts):
        """Construct colored text.

        Each arguments may be:
            - a simple string
            - other ColoredText object
        """
        self.scrlen = 0
        self.parts = []  # list of _ColoredChunk
        for part in parts:
            self += part

    @classmethod
    def make(cls, color_prefix, text, color_suffix):
        """Construct ColoredText with explicit escape sequences."""
        return cls(cls._ColoredChunk(color_prefix, text, color_suffix))

    def __str__(self):
        # produce colored text
        return "".join(f"{p.c_prefix}{p.text}{p.c_suffix}" for p in self.parts)

    def __len__(self):
        return self.scrlen

    def __eq__(self, other):
        """ColoredText objects are equal if have same text and same color.

        ColoredText with no color considered equal to raw string.
        """
        if self is other:
            return True

        if isinstance(other, ColoredText):
            if len(self.parts) != len(other.parts):
                return False
            return all(p0._equal(p1) for p0, p1 in zip(self.parts, other.parts))

        if isinstance(other, str):
            if len(self.parts) != 1:
                return not self.parts and not other

            p = self.parts[0]
            return p.c_prefix == "" and p.text == other and p.c_suffix == ""

        return NotImplemented

    def no_color(self):
        """produce not-colored text"""
        return "".join(part.text for part in self.parts)

    def __iadd__(self, other):
        """add some text (colored or usual) to self"""
        if isinstance(other, (list, tuple)):
            for part in other:
                self += part
        elif hasattr(other, 'c_prefix'):
            self._append_colored_chunk(other)
        elif hasattr(other, 'parts') and hasattr(other, 'scrlen'):
            # looks like this is another ColoredText object
            try_merge = True
            for part in other.parts:
                self._append_colored_chunk(part, try_merge)
                try_merge = False
        else:
            self._append_colored_chunk(self._ColoredChunk("", str(other), ""))

        return self

    def __add__(self, other):
        """Concatenate color text objects"""
        result = ColoredText(self)
        result += other
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

    def _append_colored_chunk(self, part, try_merge=True):
        # append _ColoredChunk to self
        if try_merge and self.parts and part.c_prefix == self.parts[-1].c_prefix:
            self.parts[-1].text += part.text
        else:
            self.parts.append(part._clone())
        self.scrlen += len(part.text)


class Palette:
    """Simple mapping 'syntax_name' -> ColorFmt"""

    def __init__(self, colors, use_colors=True):
        self.colors = colors.copy()
        self.use_colors = use_colors

    def get_color(self, syntax_name):
        """syntax_name -> ColorFmt"""
        no_color = ColorFmt.get_nocolor_fmt()

        if not self.use_colors:
            return no_color

        return self.colors.get(syntax_name, no_color)


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
            return cls.get_nocolor_fmt()
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
            return cls.get_nocolor_fmt()

        raise ValueError(f"Invalid arg {color_obj} for ColorFmt")

    @classmethod
    def get_nocolor_fmt(cls):
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
