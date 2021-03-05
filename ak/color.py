"""Methods for printing colored text.

Example of usage:
    green_printer = ColorPrinter('GREEN')
    t = green_printer("some green text") + " and normal text "
    t += [" and ", ColorPrinter('RED')("some red text")]

    # produce string with color excape sequences
    str(t)

    # produce string with same text but no color escape sequences
    t_no_color = t.no_color()
"""


#########################
# Color printer

class _ColoredChunk:
    # """Colored text. All text has same color."""
    __slots__ = '_c_prefix', 'text', '_c_suffix'
    def __init__(self, prefix, text, suffix):
        self._c_prefix = prefix
        self.text = text
        self._c_suffix = suffix


class ColoredText:
    """Colored text. Consists of several mono-colored parts."""

    def __init__(self, *parts):
        """Construct colored text.

        Each arguments may be:
            - a simple string
            - other ColoredText object
            - _ColoredChunk object
        """
        self.scrlen = 0
        self.parts = []  # list of _ColoredChunk
        for part in parts:
            self += part

    @classmethod
    def make_colored(cls, color_prefix, text, color_suffix):
        """Construct ColoredText with explicit escape sequences."""
        return cls(_ColoredChunk(color_prefix, text, color_suffix))

    def __str__(self):
        # produce colored text
        return "".join(f"{p._c_prefix}{p.text}{p._c_suffix}" for p in self.parts)

    def no_color(self):
        """produce not-colored text"""
        return "".join(part.text for part in self.parts)

    def __iadd__(self, other):
        """add some text (colored or usual) to self"""
        if isinstance(other, list) or isinstance(other, tuple):
            for part in other:
                self += part
        elif hasattr(other, '_c_prefix'):
            self._append_colored_chunk(other)
        elif hasattr(other, 'parts') and hasattr(other, 'scrlen'):
            # looks like this is another ColoredText object
            try_merge = True
            for part in other.parts:
                self._append_colored_chunk(part, try_merge)
                try_merge = False
        else:
            self._append_colored_chunk(_ColoredChunk("", str(other), ""))

        return self

    def __add__(self, other):
        """Concatenate color text objects"""
        result = ColoredText(self)
        result += other
        return result

    def _append_colored_chunk(self, part, try_merge=True):
        # append _ColoredChunk to self
        if try_merge and self.parts and part._c_prefix == self.parts[-1]._c_prefix:
            self.parts[-1].text += part.text
        else:
            self.parts.append(part)
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

    BOLD, NORMAL, DARK = range(3)
    _BOLD_CODES = ["1", "22", "2"]

    def __init__(
            self, color,
            bg_color=None, bold=None, underline=None, blink=None, crossed=None):
        """Create an object which converts text to text with specified color"""
        assert color is None or color in self._COLORS
        assert bg_color is None or bg_color in self._COLORS

        color_codes = []
        if color is not None:
            color_codes.append(self._COLORS[color])

        if bg_color is not None:
            color_codes.append("4" + self._COLORS[bg_color][1:])

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
        return ColoredText.make_colored(self._color_prefix, text, self._color_suffix)
