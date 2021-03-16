"""Methods for pretty-printing tables and json-like python objects."""

from ak.color import ColorFmt


class PrettyPrinter:
    """Print json-like objects with color highliting."""

    # dafault colors
    _COLOR_NAME = ColorFmt('GREEN', bold=True)
    _COLOR_NUMBER = ColorFmt('YELLOW')
    _COLOR_KEYWORD = ColorFmt('BLUE', bold=True)
    _NO_COLOR = ColorFmt(None)

    def __init__(
            self, *,
            color_name=_COLOR_NAME,
            color_number=_COLOR_NUMBER,
            color_keyword=_COLOR_KEYWORD,
            use_colors=True):
        """Create PrettyPrinter for printing json-like objects.

        Arguments:
        - color_name: specifies how keys of dicts are formatted.
        - color_number: specifies how number values are formatted.
        - color_keyword: specifies format for 'True', 'False' and 'None' constants
        - use_colors: if False, the "color_*" arguments are ignored and
            plain text is produced.
        Each 'color_*" argument can be be either:
            - ColorFmt object
            - color name string
            - tuple of ("color name", {effect_name: value}).
              Check ColorFmt constructor for possible values of color
              and effects.
            - None (to use text w/o any effects)
        """
        self._color_name = self._mk_color_fmt(color_name, use_colors)
        self._color_number = self._mk_color_fmt(color_number, use_colors)
        self._color_keyword = self._mk_color_fmt(color_keyword, use_colors)

    def pretty_print(self, obj_to_print):
        """Generic pretty print of json-like python objects."""
        print(self.make_pp_str(obj_to_print))

    def make_pp_str(self, obj_to_print):
        """Make a pretty string representation of json-like python object."""
        return "".join(
            line for line in self._gen_pp_str_for_obj(obj_to_print, offset=0))

    def _mk_color_fmt(self, arg, use_colors):
        if not use_colors:
            return self._NO_COLOR
        elif isinstance(arg, ColorFmt):
            return arg
        elif isinstance(arg, str):
            return ColorFmt(arg)
        elif isinstance(arg, tuple):
            assert len(arg) == 2, (
                f"Invalid arg for ColorFmt: {arg}. "
                f"Expected tuple of two elements: color_name and dict"
            )
            return ColorFmt(arg[0], **arg[1])
        elif arg is None:
            return self._NO_COLOR

        raise ValueError(f"Invalid arg {arg} for ColorFmt")

    def _gen_pp_str_for_obj(self, obj_to_print, offset=0):
        # generate parts for 'make_pp_str' method
        if self._value_is_simple(obj_to_print):
            yield str(self._colorp_simple_value(obj_to_print))
        elif isinstance(obj_to_print, dict):
            sorted_keys = sorted(
                obj_to_print.keys(), key=self._mk_type_sort_value
            )
            if self._all_values_are_simple(obj_to_print):
                # check if it is possible to print object in one line
                chunks = [
                    self._colorp_dict_key(key) + ": " + self._colorp_simple_value(
                        obj_to_print[key])
                    for key in sorted_keys
                ]
                # note, next line calculates length of text as printed on screen
                scr_len = sum(len(chunk) for chunk in chunks) + 2 * len(chunks)
                oneline_fmt = offset + scr_len < 200  # !!!!! not exactly correct
                if oneline_fmt:
                    yield "{" + ", ".join(str(c) for c in chunks) + "}"
                    return

            # print object in multiple lines
            yield "{"
            prefix = "\n" + " " * (offset + 2)
            is_first = True
            for key in sorted_keys:
                if is_first:
                    is_first = False
                else:
                    yield ","
                yield prefix
                yield str(self._colorp_dict_key(key))
                yield ": "
                yield from self._gen_pp_str_for_obj(obj_to_print[key], offset+2)
            yield "\n" + " " * offset + "}"
        elif isinstance(obj_to_print, list):
            if self._all_values_are_simple(obj_to_print):
                # check if it is possible to print values in one line
                chunks = [
                    self._colorp_simple_value(item) for item in obj_to_print
                ]
                scr_len = sum(len(chunk) for chunk in chunks) + 2 * len(chunks)
                oneline_fmt = offset + scr_len < 200
                if oneline_fmt:
                    yield "[" + ", ".join(str(c) for c in chunks) + "]"
                    return

            # print object in multiple lines
            else:
                prefix = "\n" + " " * (offset + 2)
                yield "["
                is_first = True
                for item in obj_to_print:
                    if is_first:
                        is_first = False
                    else:
                        yield ","
                    yield prefix
                    yield from self._gen_pp_str_for_obj(item, offset+2)
                yield "\n" + " " * offset + "]"
        else:
            yield str(obj_to_print)

    @classmethod
    def _all_values_are_simple(cls, obj_to_print):
        # checks if all the values in container are 'simple'
        if isinstance(obj_to_print, dict):
            return all(cls._value_is_simple(value) for value in obj_to_print.values())
        if isinstance(obj_to_print, (list, tuple)):
            return all(cls._value_is_simple(value) for value in obj_to_print)
        return True

    @classmethod
    def _value_is_simple(cls, value):
        # values that pretty printer treats as simple when deciding
        # how to print the value
        if isinstance(value, (list, tuple, dict)) and value:
            return False
        return True

    def _colorp_simple_value(self, value):
        # value -> formatted string
        if isinstance(value, str):
            return '"' + value + '"'
        elif isinstance(value, (int, float)):
            return self._color_number(str(value))
        elif value in (True, False, None):
            return self._color_keyword(str(value))
        elif isinstance(value, dict):
            assert not value
            return "{}"
        elif isinstance(value, (list, tuple)):
            assert not value
            return "[]"
        assert False, "value is not simple"
        return None

    def _colorp_dict_key(self, key):
        # dictionary key -> formatted string
        if isinstance(key, str):
            return self._color_name('"' + key + '"')
        else:
            return self._color_name(str(key))

    @classmethod
    def _mk_type_sort_value(cls, value):
        # sorting used to order dictionari elements when printing
        if isinstance(value, (int, float)):
            return (0, value)
        elif isinstance(value, str):
            return (1, value)
        elif isinstance(value, tuple):
            return (2, value)
        else:
            return (3, str(value))
