"""Methods for printing colored text.

ColoredText - objects of this class are string-like objects, which can be
    converted to usual strings, containing color escape sequences.
    One of the problems with raw strings with escape sequences is that
    the length of the string is different from the number of printed
    characters. As a result it's not possible to use 'width' format
    specifier when formatting such strings.
    ColoredText objects can be printed using format specifiers.

ColorPrinter - class which produces ColoredText objects.

Example of usage:
    green_printer = ColorPrinter('GREEN')
    t = green_printer("some green text") + " and normal text "
    t += [" and ", ColorPrinter('RED')("some red text")]

    # produce string with color excape sequences
    str(t)
    # produce a string, which will take 100 places on screen
    f"{t: ^100}"

    # produce string with same text but no color escape sequences
    t_no_color = t.no_color()
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


class ColorPrinter:
    """Objects of this class produce colored text."""

    __slots__ = '_color_prefix', '_color_suffix'

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
        if color is not None and color not in self._COLORS:
            raise ValueError(
                f"Invalid color name '{color}' specified. "
                f"Valid color names: {self._COLORS.keys()}")
        if bg_color is not None and bg_color not in self._COLORS:
            raise ValueError(
                f"Invalid bg_color name '{bg_color}' specified. "
                f"Valid color names: {self._COLORS.keys()}")

        color_codes = []
        if use_effects:
            if color is not None:
                color_codes.append(self._COLORS[color])

            if bg_color is not None:
                color_codes.append("4" + self._COLORS[bg_color][1:])

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
            self._color_prefix = "\033[" + ";".join(c for c in color_codes) + "m"
            self._color_suffix = "\033[0m"
        else:
            self._color_prefix = ""
            self._color_suffix = ""

    def __call__(self, text):
        """text -> colored text (ColoredText object)."""
        return ColoredText.make(self._color_prefix, text, self._color_suffix)
