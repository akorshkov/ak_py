"""Methods for pretty-printing tables and json-like python objects.

Classes provided by this module:
- PrettyPrinter - pretty-printer of json-like python structures
- PPObj - base class for objects which have colored text representation
- PPWrap - Pretty-printable wrapper to be used in interactive console
- PPTable - pretty-printable 2-D tables
- PPEnumFieldType - to be used by PPTable for enum fields
"""

# - FieldType       - general properties of a field. Defines how to display misc
#                     values in representation column. It implements default
#                     representation for values of a symple types (ints, strings,
#                     etc.)
# - FieldValueType  - if the value of a field is an instance of this class,
#                     then the value itself produces it's representation.
# - RecordField     - field type and it's location in a record
# - RecordStructure - all the fields in a record
# - ReprColumn      - field, widths, fmt_modifier
# - ReprStructure   - RecordStructure + columns. Described by 'fmt'


from typing import Iterator
from numbers import Number
from dataclasses import dataclass
from collections import defaultdict
from ak import utils
from ak.color import CHText, Palette, CompoundPalette, PaletteUser, ConfColor


class CHTextResult:
    """Can be used either as a CHText object, or as CHText lines iterator.

    Single PPObj object can either produce a single CHText or generate multiple
    CHText objects (usually corresponding to single lines of the multi-line text).
    CHTextResult produced by PPObj may be used in both contexts.
    """
    __slots__ = ('_ch_text', )

    def __init__(self):
        self._ch_text = None

    def _make_ch_text(self) -> CHText:
        raise NotImplementedError(f"'_make_ch_text' not implemented in {type(self)}")

    def _make_ch_lines_iter(self) -> Iterator[CHText]:
        raise NotImplementedError(
            f"'_make_ch_lines_iter' not implemented in {type(self)}")

    def __str__(self):
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return self._ch_text.__str__()

    def plain_text(self) -> str:
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return self._ch_text.plain_text()

    @classmethod
    def strip_colors(cls, text: str) -> str:
        """Colorer-formatted string -> same string w/o coloring."""
        return CHText.strip_colors(text)

    def get_ch_text(self) -> CHText:
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return CHText(self._ch_text)

    def __len__(self):
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return len(self._ch_text)

    def __iadd__(self, other) -> CHText:
        return self + other

    def __add__(self, other) -> CHText:
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return self._ch_text + other

    def __radd__(self, other) -> CHText:
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return other + self._ch_text

    def __getitem__(self, index) -> CHText:
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return self._ch_text.__getitem__(index)

    def fixed_len(self, desired_len) -> CHText:
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return self._ch_text.fixed_len(desired_len)

    def __format__(self, format_spec):
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        return self._ch_text.__format__(format_spec)

    def __eq__(self, other):
        if self._ch_text is None:
            self._ch_text = self._make_ch_text()
        if isinstance(other, CHTextResult):
            other = other.get_ch_text()
        return self._ch_text.__eq__(other)

    def __iter__(self):
        return self._make_ch_lines_iter()


class CHTextPPobjResult(CHTextResult):
    """Can be used either as a CHText object, or as CHText lines iterator.

    Implementation of CHTextResult when the source of CHText is PPObj.
    """
    __slots__ = 'ppobj', 'cp'

    def __init__(self, ppobj, cp):
        self.ppobj = ppobj
        self.cp = cp
        super().__init__()

    def _make_ch_text(self) -> CHText:
        return self.ppobj.make_ch_text(self.cp)

    def _make_ch_lines_iter(self) -> Iterator[CHText]:
        return self.ppobj.gen_ch_lines(self.cp)


class CHTextFixedListResult(CHTextResult):
    """Can be used either as a CHText object, or as CHText lines iterator.

    Implementation of CHTextResult when the source of CHText is a list
    of CHText objects.
    """
    __slots__ = ('chtext_list', )

    def __init__(self, chtext_list):
        self.chtext_list = chtext_list
        super().__init__()

    def _make_ch_text(self) -> CHText:
        return CHText("\n").join(self.chtext_list)

    def _make_ch_lines_iter(self) -> Iterator[CHText]:
        yield from self.chtext_list


#########################
# generic pretty-printing

class PrettyPrinter(PaletteUser):
    """Print json-like python objects with color highliting."""

    _CONSTANTS_LITERALS = (
        {True: 'True', False: 'False', None: 'None'},
        {True: 'true', False: 'false', None: 'null'},
    )

    class PPPalette(Palette):
        """Palette to be used by PrettyPrinter."""
        name = ConfColor("NAME")
        number = ConfColor("NUMBER")
        keyword = ConfColor("KEYWORD")

    PALETTE_CLASS = PPPalette

    def __init__(self, *, fmt_json=False):
        """Create PrettyPrinter for printing json-like objects.

        Arguments:
        - fmt_json: if True generate output in json form, else - in python form.
            The difference is in value of constans only ('true' vs 'True', etc.)
        """
        self._consts = self._CONSTANTS_LITERALS[1 if fmt_json else 0]

    def __call__(
        self, obj_to_print, *,
        palette=None,
        no_color=None,
        compound_palette=None,
        shade_name=None,
    ) -> CHTextResult:
        """obj_to_print -> pretty-printed colored text.

        Arguments:
        - obj_to_print: object to print
        - palette: optional PrettyPrinter.PPPalette-derived class or an object of
            such class, contains colors to be used
        - no_color: optional bool; True indicates that produced text will contain
            no colors
        - compound_palette: can be specified if the palette to use is a part of
            the palette of some bigger object. Check CompoundPalette doc for more
            details.
        - shade_name: additional parameter for identication of the required palette
            in the compound_palette.
        """
        palette = self._mk_palette(palette, no_color, compound_palette, shade_name)
        ppobj = _PrettyPrinterTextGen(self, obj_to_print)
        return CHTextPPobjResult(ppobj, palette)

    def _gen_ch_lines(self, cp, obj_to_print) -> Iterator[CHText]:
        """obj_to_print -> CHText objects.

        Each CHText corresponds to one line of the result.
        """
        line_chunks = []

        for chunk in self._gen_ch_chunks_for_obj(cp, obj_to_print, offset=0):
            if chunk is None:
                # indicator of the new line
                yield CHText.make(line_chunks)
                line_chunks = []
            else:
                line_chunks.append(chunk)

        if line_chunks:
            yield CHText.make(line_chunks)

    def _gen_ch_chunks_for_obj(
        self, cp: PPPalette, obj_to_print, offset=0,
    ) -> Iterator[CHText.Chunk]:
        # generate parts for colored text result

        if self._value_is_simple(obj_to_print):
            yield self._simple_val_to_ch_chunk(cp, obj_to_print)
        elif isinstance(obj_to_print, dict):
            sorted_keys = sorted(
                obj_to_print.keys(), key=self._mk_type_sort_value
            )
            if self._all_values_are_simple(obj_to_print):
                # check if it is possible to print object in one line
                chunks = [cp.text("{")]
                is_first = True
                for key in sorted_keys:
                    if not is_first:
                        chunks.append(cp.text(", "))
                    else:
                        is_first = False
                    chunks.append(self._dict_key_to_sc_chunk(cp, key))
                    chunks.append(cp.text(": "))
                    chunks.append(self._simple_val_to_ch_chunk(
                        cp, obj_to_print[key]))
                chunks.append(cp.text("}"))
                scr_len = CHText.calc_chunks_len(chunks)

                oneline_fmt = offset + scr_len < 200  # not exactly correct, ok
                if oneline_fmt:
                    yield from chunks
                    return

            # print object in multiple lines
            yield cp.text("{")
            prefix = cp.text(" " * (offset + 2))
            is_first = True
            for key in sorted_keys:
                if is_first:
                    is_first = False
                else:
                    yield cp.text(",")
                yield None
                yield prefix
                yield self._dict_key_to_sc_chunk(cp, key)
                yield cp.text(": ")
                yield from self._gen_ch_chunks_for_obj(
                    cp, obj_to_print[key], offset+2)
            yield None
            yield cp.text(" " * offset + "}")
        elif isinstance(obj_to_print, list):
            if self._all_values_are_simple(obj_to_print):
                # check if it is possible to print values in one line
                items_chunks = [
                    self._simple_val_to_ch_chunk(cp, item)
                    for item in obj_to_print
                ]
                scr_len = (
                    CHText.calc_chunks_len(items_chunks) + 2 * len(items_chunks))
                oneline_fmt = not items_chunks or offset + scr_len < 200
                if oneline_fmt:
                    # print the list in one line
                    yield cp.text("[")
                    is_first = True
                    for item_chunk in items_chunks:
                        if is_first:
                            is_first = False
                        else:
                            yield cp.text(", ")
                        yield item_chunk
                    yield cp.text("]")
                else:
                    # print the list in several lines (but each line may
                    # contain several values)
                    yield cp.text("[")
                    yield None
                    prefix = cp.text(" " * (offset + 2))
                    len_yielded = 0
                    is_first_in_line = True
                    for i, item_chunk in enumerate(items_chunks):
                        cur_chunk_len = len(item_chunk.text)
                        need_new_line = len_yielded + cur_chunk_len > 150

                        if need_new_line and not is_first_in_line:
                            yield cp.text(",")
                            yield None
                            len_yielded = 0
                            is_first_in_line = True

                        if is_first_in_line:
                            yield prefix
                            len_yielded = offset + 2
                        else:
                            yield cp.text(", ")
                            len_yielded += 2
                        yield item_chunk
                        len_yielded += cur_chunk_len
                        is_first_in_line = False

                        if i == len(items_chunks) - 1:
                            # last element of the list
                            yield None
                            break
                    # all items printed, new line started
                    yield cp.text(" " * offset + "]")
            # print object in multiple lines
            else:
                prefix = cp.text(" " * (offset + 2))
                yield cp.text("[")
                is_first = True
                for item in obj_to_print:
                    if is_first:
                        is_first = False
                    else:
                        yield cp.text(",")
                    yield None
                    yield prefix
                    yield from self._gen_ch_chunks_for_obj(cp, item, offset+2)
                yield None
                yield cp.text(" " * offset + "]")
        else:
            yield cp.text(str(obj_to_print))

    @classmethod
    def _all_values_are_simple(cls, obj_to_print) -> bool:
        # checks if all the values in container are 'simple'
        if isinstance(obj_to_print, dict):
            return all(cls._value_is_simple(value) for value in obj_to_print.values())
        if isinstance(obj_to_print, (list, tuple)):
            return all(cls._value_is_simple(value) for value in obj_to_print)
        return True

    @classmethod
    def _value_is_simple(cls, value) -> bool:
        # values that pretty printer treats as simple when deciding
        # how to print the value
        if isinstance(value, (list, tuple, dict)) and value:
            return False
        return True

    def _simple_val_to_ch_chunk(self, cp: PPPalette, value) -> CHText.Chunk:
        # simple value (number, string, built-in constant) -> CHText.Chunk
        if isinstance(value, str):
            return cp.text('"' + value + '"')
        elif self.is_keyword_value(value):
            return cp.keyword(self._consts[value])
        elif isinstance(value, Number):
            return cp.number(str(value))
        elif isinstance(value, dict):
            assert not value
            return cp.text("{}")
        elif isinstance(value, (list, tuple)):
            assert not value
            return cp.text("[]")
        assert False, f"value {value} is not simple"

    def _dict_key_to_sc_chunk(self, cp: PPPalette, key) -> CHText.Chunk:
        # create colored text corresponding to a dictionary key
        key_str = '"' + key + '"' if isinstance(key, str) else str(key)
        return cp.name(key_str)

    @classmethod
    def _mk_type_sort_value(cls, value):
        # sorting used to order dictionary elements when printing
        if cls.is_keyword_value(value):
            return (3, str(value))
        elif isinstance(value, Number):
            return (0, value)
        elif isinstance(value, str):
            return (1, value)
        elif isinstance(value, tuple):
            return (2, value)
        else:
            return (3, str(value))

    @staticmethod
    def is_keyword_value(value):
        """Check if value is one of {True, False, None}.

        Simple check 'x in {True, False, None}' can't be used because it
        returns True for x = 1
        """
        return any(value is keyword for keyword in [True, False, None])


class _PrettyPrinterTextGen:
    # PPObj-looking object which produces pretty-print results
    __slots__ = 'pretty_printer', 'obj_to_print'
    def __init__(self, pretty_printer, obj_to_print):
        self.pretty_printer = pretty_printer
        self.obj_to_print = obj_to_print

    def make_ch_text(self, cp):
        return CHText("\n").join(self.gen_ch_lines(cp))

    def gen_ch_lines(self, cp):
        return self.pretty_printer._gen_ch_lines(cp, self.obj_to_print)


class PPObj(PaletteUser):
    """Base class for pretty-printable objects.

    Object of PPObj class has a colored-text representation. For example we want to
    print a table using different colors for table borders, column headers and
    cells contents.

    The '__str__' method of the PPObj produces the colored text: string with color
    escape sequences. But the string with escape sequences is not convenient to
    work with: the length of the string is not equal to the number of printable
    characters.

    In order to make it possible to format colored text CHText is used.
    CHText object keeps track of printable and not-printable characters, so that
    it is possible to use it in f-strings with width format specifiers.

    PPObj.ch_text() method returns ak.color.CHTextResult object. This object is
    similar to CHText, but can be used as iterator of CHText objects (usualy
    corresponding to the lines of multi-line text)

    PPObj-derived class should implement at least one of the two methods:
    - make_ch_text(cp: Palette) -> CHText
    - gen_ch_lines(cp: Palette) -> Iterator[CHText]

    (See PaletteUser class documentation for more details).
    """

    def __str__(self):
        return str(self.ch_text())

    def ch_text(
        self, *, palette=None, no_color=None,
        compound_palette=None, shade_name=None,
    ) -> CHTextResult:
        """Return CHTextResult - colored representation of self.

        Arguments:
        - palette: (optional) Either Palette-derived class or an object of such type
        - no_color: instructs to produce text without color effects,
            False by default
        - compound_palette: can be specified if the object's palette is a part of
            the palette of some bigger object. Check CompoundPalette doc for more
            details.
        - shade_name: additional parameter for identication of the required palette
            in the compound_palette.
        """
        return CHTextPPobjResult(
            self,
            self._mk_palette(palette, no_color, compound_palette, shade_name))

    def make_ch_text(self, cp: Palette) -> CHText:
        """Return CHText - colored representation of self"""
        try:
            lines = self.gen_ch_lines(cp)
            return CHText("\n").join(lines)
        except NotImplementedError as err:
            if 'gen_ch_lines' not in str(err):
                raise

        raise NotImplementedError(f"'make_ch_text' not implemented in '{type(self)}'")

    def gen_ch_lines(self, cp: Palette) -> Iterator[CHText]:
        """Generates CHText objects - colored representation of self"""
        yield from []
        _ = cp
        raise NotImplementedError(f"'gen_ch_lines' not implemented in '{type(self)}'")


# ready to use PrettyPrinter with default configuration
pp = PrettyPrinter()


#########################
# pretty-printing json-like python objects

class PPWrap:
    """Pretty-printable wrapper for python json-like structures.

    To be used in interactive console.

    Example scenario of usage:

    Some function returns a json parsed into python structure: some_result.
    The version of this function which is supposed to be used in an interactive
    console should return x = PPWrap(some_result).

    Repr of this object prints the structure in a pretty-formatted colored form.
    The original data is accessible via 'r' attribute:

    x.r is some_result
    """

    __slots__ = ('r', )
    _PPRINTER = PrettyPrinter()

    def __init__(self, obj_to_print):
        self.r = obj_to_print

    def __str__(self):
        return str(self._PPRINTER(self.r))

    def __repr__(self):
        # this method does not return text but prints it because the
        # text is supposed to be colored, and python console displays
        # representation of of returned object (a string with special characters
        # in this case) instead of the colored text.
        print(str(self))
        return ""


##################################################
# Records
#
# Term "records" is used for a set of objects having similar structure.
# In simple cases the structure of the record may be a tuple of simple values (for
# example for records fetched from database).
#
# In more complicated cases it may be a composition of tuples, lists, dictionaries
# and other python objects.
#
# The purpose of the following record-related classes is to facilitate
# processing records and presenting data from the records on screen.


#########################
# class FieldType

class FieldType(PaletteUser):
    """Describe properties of a field (in a record).

    The main purpose of this class is to format the field's value.

    This class implements default representation for simple values (numbers,
    strings, etc.)

    Not trivial example of the FieldType is a enum. The value is just an id,
    but we may want to display (or not to display) the corresponding name as well.

    FieldType should implement the following methods:
    - make_desired_cell_ch_chunks: returns "desired text"(*) and alignment
    - get_cell_text_len: return length of the "desired text"(*)
    - make_cell_ch_chunks: returns properly trancated or enlarged "desired text"(*)
        to fit specified length.

    (*) "desired text" is a colored text representing the value. Actual text may
    be different if it is necessary to fit the text into a cell of a specified width.
    For performance reasons it is not a CHText object, but [CHText.Chunk].
    """

    ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT = 1, 2, 3

    class RecordPalette(Palette):
        """Palette used for field values of standard types."""
        SYNTAX_DEFAULTS = {
            # synt_id: default_color
            'RECORD.NUMBER': "NUMBER",
            'RECORD.KEYWORD': "KEYWORD",
        }

        number = ConfColor('RECORD.NUMBER')
        keyword = ConfColor('RECORD.KEYWORD')

    PALETTE_CLASS = RecordPalette

    _DFLT_MIN_WIDTH = 1
    _DFLT_MAX_WIDTH = 999

    def __init__(self, min_width=None, max_width=None):
        self.min_width = self._DFLT_MIN_WIDTH if min_width is None else min_width
        self.max_width = self._DFLT_MAX_WIDTH if max_width is None else max_width
        assert self.min_width <= self.max_width

    def get_cell_text_len(self, value, fmt_modifier) -> int:
        """Calculate length of text representation of the value (for usual cell)

        This implementation is universal, but inefficient. Override in
        derived classes to avoid construction of CHText.Chunk objects - usually
        it is not required to find out text length.
        """
        ch_text_chunks, _ = self.make_desired_cell_ch_chunks(
            value, fmt_modifier,
            self.PALETTE_CLASS(no_color=True))
        return CHText.calc_chunks_len(ch_text_chunks)

    def make_desired_cell_ch_chunks(
        self, value, fmt_modifier, field_palette,
    ) -> ([CHText.Chunk], int):
        """value -> desired text and alignment for usual (not title) table row.

        Actual text may be truncated (hence different from desired text)

        Implementation for general field type: value printed almost as is.
        To be overiden in derived classes.
        """
        cp = field_palette
        if fmt_modifier is not None:
            raise ValueError(
                f"{type(self)} field type does not support format modifiers. "
                f"Specified fmt_modifier: '{fmt_modifier}'")
        if PrettyPrinter.is_keyword_value(value):
            color_fmt = cp.keyword
            align = self.ALIGN_RIGHT
        elif isinstance(value, Number):
            color_fmt = cp.number
            align = self.ALIGN_RIGHT
        else:
            color_fmt = cp.text
            align = self.ALIGN_LEFT
        return [color_fmt(str(value))], align

    def make_cell_ch_chunks(
        self, value, fmt_modifier, width, record_palette,
    ) -> [CHText.Chunk]:
        """value -> [CHText.Chunk] having exactly specified width."""

        field_palette = record_palette.get_sub_palette(self.PALETTE_CLASS)

        text, align = self.make_desired_cell_ch_chunks(
            value, fmt_modifier, field_palette)

        return self.fit_to_width(text, width, align, record_palette)

    def _verify_fmt_modifier(self, fmt_modifier):
        # Raise exc if 'fmt_modifier' is not compatible with this field type.
        ok, err_msg = self.is_fmt_modifier_ok(fmt_modifier)
        if not ok:
            raise ValueError(err_msg)

    def is_fmt_modifier_ok(self, fmt_modifier) -> [bool, str]:
        """Chek if fmt_modifier is correct.

        To be overriden in derived classes. By default Field Types do not
        accept any format modifiers.
        """
        if fmt_modifier is None:
            return True, ""
        return False, (
            f"Field type {self} does not support format modifiers. "
            f"(specified format modifier: '{fmt_modifier}')")

    @classmethod
    def fit_to_width(cls, ch_chunks, width, align, cp) -> [CHText.Chunk]:
        """[CHText.Chunk] -> [CHText.Chunk] of exactly specified length.

        Arguments:
        - ch_chunks: may be one of:
            - list of CHText.Chunk objects
            - single CHText.Chunk
            - CHText
        - width: desired width of result
        - align: FieldType.ALIGN_LEFT or FieldType.ALIGN_CENTER
            or FieldType.ALIGN_RIGHT
        - cp: record's color palette

        Return value:
        Method always returns [CHText.Chunk].

        Examples:
        'short'            -> colored 'short    '  or '    short'
        'very long text'   -> colored 'very l...'
        """
        if not isinstance(ch_chunks, list):
            if isinstance(ch_chunks, CHText.Chunk):
                ch_chunks = [ch_chunks]
            elif isinstance(ch_chunks, CHText):
                ch_chunks = ch_chunks.chunks.copy()

        assert width >= 0
        filler_len = width - CHText.calc_chunks_len(ch_chunks)
        if filler_len == 0:
            return ch_chunks  # lucky, the text has exactly necessary length
        if filler_len > 0:
            if align == cls.ALIGN_CENTER:
                left_filer_len = filler_len // 2
                right_filler_len = filler_len - left_filer_len
                result = [cp.text(' '*left_filer_len)]
                result.extend(ch_chunks)
                result.append(cp.text(' '*right_filler_len))
                return result
            filler = cp.text(' '*filler_len)
            if align == cls.ALIGN_LEFT:
                return ch_chunks + [filler, ]
            assert align == cls.ALIGN_RIGHT
            result = [filler, ]
            result.extend(ch_chunks)
            return result
        # text is longer than necessary. It needs to be truncated.
        # "some long text" -> "some lo..."
        dots_len = min(3, width)
        visible_text_len = width - dots_len

        result = CHText.resize_chunks_list(ch_chunks, visible_text_len)
        result.append(cp.warn('.'*dots_len))

        return result


class _DefaultFieldType(FieldType):
    # Default FieldType to be used for fields with simple values.
    # Implements more efficient get_cell_text_len

    def get_cell_text_len(self, value, fmt_modifier):
        """Calculate length of text representation of the value."""
        # caluculate text length w/o constructing CHText object for the cell
        return len(str(value))


class _DefaultTitleFieldType(_DefaultFieldType):
    # Default field type which produces content for titles (for example for
    # title cells of a table)

    class TitlePalette(FieldType.PALETTE_CLASS):
        SYNTAX_DEFAULTS = {
            # synt_id: default_color
            'RECORD.TITLE': "GREEN:bold",
            'RECORD.COL_TITLE': "GREEN:bold",
        }

        title = ConfColor('RECORD.TITLE')
        col_title = ConfColor('RECORD.COL_TITLE')

    PALETTE_CLASS = TitlePalette

    def make_desired_cell_ch_chunks(
        self, value, fmt_modifier, field_palette,
    ) -> ([CHText.Chunk], int):
        """Make desired content for title."""
        if isinstance(value, str) and fmt_modifier is None:
            return field_palette.col_title(value), self.ALIGN_LEFT
        return super().make_desired_cell_ch_chunks(value, fmt_modifier, field_palette)


class FieldValueType(PaletteUser):
    """More complex values of fields.

    This class provides functionality similar to the functionality provided
    by 'FieldType' calss. The difference is that 'FieldType' objects format given
    values to be displayed in a record column. Objects of 'FieldValueType' ARE the
    values which can produce representation of self for a record column.

    Names of the mothods the derived class should implement are the same as in
    'FieldType' class. But these methods do not accept the 'value' argument:

    - make_desired_cell_ch_chunks: returns "desired text" and alignment
    - get_cell_text_len: return length of the "desired text"
    - make_cell_ch_chunks: returns properly trancated or enlarged "desired text"
        to fit specified length.
    """

    ALIGN_LEFT = FieldType.ALIGN_LEFT
    ALIGN_CENTER = FieldType.ALIGN_CENTER
    ALIGN_RIGHT = FieldType.ALIGN_RIGHT

    PALETTE_CLASS = FieldType.RecordPalette

    def make_desired_cell_ch_chunks(
        self, fmt_modifier, field_palette,
    ) -> ([CHText.Chunk], int):
        raise NotImplementedError(
            f"'make_desired_cell_ch_chunks' is not implemented in '{type(self)}'")

    def get_cell_text_len(self, fmt_modifier):
        """Calculate length of text representation of self (for usual cell)

        This implementation is universal, but inefficient. Override in
        derived classes to avoid construction of CHText.Chunk objects - usually
        it is not required to find out text length.
        """
        ch_text_chunks, _ = self.make_desired_cell_ch_chunks(
            fmt_modifier, self.PALETTE_CLASS(no_color=True))
        return CHText.calc_chunks_len(ch_text_chunks)

    def make_cell_ch_chunks(
        self, fmt_modifier, width, record_palette,
    ) -> [CHText.Chunk]:
        """self -> [CHText.Chunk] having exactly specified width."""
        field_palette = record_palette.get_sub_palette(self.PALETTE_CLASS)

        text, align = self.make_desired_cell_ch_chunks(fmt_modifier, field_palette)

        return FieldType.fit_to_width(text, width, align, record_palette)


class RecordField:
    """Describes a field in a record.

    Keeps information about the type of the field and it's location in the record.
    """

    __slots__ = 'name', 'field_type', 'value_path', 'title_lines'

    _V_PATH_ATTR, _V_PATH_KEY, _V_PATH_CONST = range(3)

    def __init__(self, name, field_type, value_path, title):
        """RecordField constructor.

        Arguments:
        - name: str, field name. Human-readable unique identifier of the field.
        - field_type: instance of FieldType
        - value_path: str, desribes location of the field value in the record object
        - title: str|list, title of the field. If it is a list or if it is a string
            containing new-line characters, it is interpreted as a multi-line title.
            By default is the same as the name.
        """
        self.name = name
        assert not isinstance(field_type, type), (
            f"invalid field_type argument. Expected instance of FieldType, got "
            f"a class object: {field_type}")
        self.field_type = field_type
        self.value_path = self._prepare_value_path(value_path, name)
        self.title_lines = list(self._gen_title_lines(title, self.name))

    def fetch_value(self, record):
        """get value from a record according to the rules specified by value_path."""
        val = record
        for v_path_type, key in self.value_path:
            if v_path_type == self._V_PATH_ATTR:
                val = getattr(val, key)
            elif v_path_type == self._V_PATH_KEY:
                val = val[key]
            else:
                assert v_path_type == self._V_PATH_CONST
                val = key
        return val

    def get_title_cell_text_len(self, fmt_modifier):
        """Get length of the field's title."""
        # Default implementation does not use fmt_modifier argument
        # pylint: disable=unused-argument
        return max(len(str(l)) for l in self.title_lines)

    @classmethod
    def _gen_title_lines(cls, title, field_name):
        # constructor helper.
        # converts the 'title' argument into a list of objects to be displayed
        # in title lines
        intermediary = None
        if title is None:
            intermediary = [field_name]
        elif isinstance(title, str):
            intermediary = [title]
        elif isinstance(title, (list, tuple)):
            intermediary = title
        else:
            intermediary = [title]

        for item in intermediary:
            if isinstance(item, str):
                yield from (l.strip() for l in item.split('\n'))
            else:
                yield item

    @classmethod
    def _prepare_value_path(cls, value_path, field_name):
        # "0.name" -> [(_V_PATH_KEY, 0), (_V_PATH_ATTR, 'name')]
        # "1.[name]" -> [(_V_PATH_KEY, 1), (_V_PATH_KEY, 'name')]
        # "0." -> [(_V_PATH_KEY, 0), (_V_PATH_ATTR, 'field_name')]
        # "=xx" -> [(_V_PATH_CONST, 'xx'), ]
        if isinstance(value_path, int):
            return [(cls._V_PATH_KEY, value_path)]
        assert isinstance(value_path, str), f"it is {type(value_path)}: {value_path}"

        prepared_path = []

        value_path = value_path.lstrip()
        if value_path.startswith('='):
            prepared_path.append((cls._V_PATH_CONST, value_path[1:]))
            return prepared_path

        steps = [s.strip() for s in value_path.split('.')]
        for step in steps:
            in_brakets = False
            if step.startswith('[') and step.endswith(']'):
                in_brakets = True
                step = step[1:-1]

            key = cls._opt_convert_int(step)
            is_attr = isinstance(key, str) and not in_brakets
            prepared_path.append(
                ((cls._V_PATH_ATTR if is_attr else cls._V_PATH_KEY), key)
            )

        if not prepared_path:
            raise ValueError(f"unexpected empty value_path: {value_path}")
        last_element = prepared_path[-1]
        if last_element[1] == '':
            # empty last element means it's the same as field name
            prepared_path[-1] = (last_element[0], field_name)

        return prepared_path

    @staticmethod
    def _opt_convert_int(text):
        # if string looks like int - convert it to int
        try:
            return int(text)
        except ValueError:
            pass
        return text


class RecordStructure:
    """Contains information about the fields in a record"""
    __slots__ = 'fields', 'map'

    def __init__(self, fields: [RecordField]):
        """Constructor of RecordStructure.

        Argument:
        - fields: list of RecordField objects. Order of the elements in the list
            defines the default order of columns in the record representation.
        """
        assert(all(isinstance(x, RecordField) for x in fields))
        self.fields = fields
        self.map = {f.name: f for f in self.fields}

        # verify no duplicates
        if len(self.fields) != len(self.map):
            d = defaultdict(int)
            for f in self.fields:
                d[f.name] += 1
            duplicates = sorted(
                field_name for field_name, count in d.items() if count > 1)
            raise ValueError(
                f"Fields in RecordStructure constructor have duplicated names: "
                f"{duplicates}")

    def get_field(self, field_name) -> RecordField:
        """Get RecordField by name. None if not found."""
        return self.map.get(field_name)


class ReprColumn:
    """Information about a single column of the record's representation.

    Do not confuse with field. Record consists of fields, record's representation
    (for example a table) consists of columns. Each column corresponds to some
    field, any number of columns may correspond to a given field.
    """

    __slots__ = (
        'field', 'name', 'fmt_modifier', 'break_by',
        'min_width', 'max_width', 'width',
    )

    def __init__(self, field, fmt_modifier=None, break_by=False,
                 min_width=None, max_width=None):
        """ReprColumn constructor.

        Arguments:
        - field: RecordField, specifies location of corresponding velue in
            record and formatting rules
        - fmt_modifier: in case RecordField supports several ways to format
            the value (f.e. long and short form of uuid) - specifies how to
            format the value.
        - break_by: indicates that an empty row should be inserted into table
            whenever the value of this column changes.
            (It is only used when the column is a part of the PPTable)
        - min_width, max_width: limits for column width.
        """
        self.field = field  # RecordField
        self.name = self.field.name

        ftype = self.field.field_type

        self.fmt_modifier = fmt_modifier  # or field.dflt_fmt_modifier
        ftype._verify_fmt_modifier(self.fmt_modifier)
        self.break_by = break_by

        self.min_width = min_width if min_width is not None else ftype.min_width
        self.max_width = max_width if max_width is not None else ftype.max_width
        self.width = None  # actual width of the column, will be calculated later

    def clone(self):
        """Clone self. (except for 'width' attribute)"""
        return ReprColumn(
            self.field,
            self.fmt_modifier,
            self.break_by,
            self.min_width,
            self.max_width,
        )

    def get_title_width(self):
        """Get width of the column's title.

        As of now columns do not have own titles, so the title of the corresponding
        field is used.
        """
        return self.field.get_title_cell_text_len(self.fmt_modifier)

    def get_cell_text_len(self, record):
        """Get desired cell length for this column when displaying given record.

        (Actual cell may be shorter or longer).
        """
        value = self.field.fetch_value(record)
        if isinstance(value, FieldValueType):
            return value.get_cell_text_len(self.fmt_modifier)
        return self.field.field_type.get_cell_text_len(value, self.fmt_modifier)

    def make_cell_ch_chunks(self, record, record_palette) -> [CHText.Chunk]:
        """Fetch value from record and make colored text for a cell.

        Length of created text is exactly self.width.
        """
        value = self.field.fetch_value(record)

        if isinstance(value, FieldValueType):
            return value.make_cell_ch_chunks(
                self.fmt_modifier, self.width, record_palette)

        return self.field.field_type.make_cell_ch_chunks(
            value, self.fmt_modifier, self.width, record_palette,
        )

    def to_fmt_str(self):
        """Create fmt string - human readable and editable descr of self."""
        fmt_str = self.name
        if self.fmt_modifier is not None:
            fmt_str += f"/{self.fmt_modifier}"

        if self.break_by:
            fmt_str += "!"

        if self.min_width == self.max_width:
            fmt_str += f":{self.min_width}"
        else:
            fmt_str += f":{self.min_width}-{self.max_width}"
            if self.width is not None:
                fmt_str += f"({self.width})"

        return fmt_str


@dataclass(frozen=True)
class RecordReprStyle:
    """Style of the record representation.

    Whether to print borders between fields and what characters to use for these
    borders - this is an example of information to keep in this class.
    But not the information about colors. Colors configuration is located
    in corresponding PALETTE_CLASS class.
    """
    inner_border: str = " "
    left_border: str = ""
    right_border: str = ""


class _ColumnsParsedFmt:
    # parsed 'fmt' string, which describes columns of record representation.

    class _ParsedColFmt(utils.DataRecord):
        # parsed information about a single column
        __slots__ = ['fmt', 'field_name', 'fmt_modifier', 'break_by',
                     'value_path', 'min_w', 'max_w']

        def mk_repr_column(self, field) -> ReprColumn:
            """self -> ReprColumn object."""
            return ReprColumn(
                field, self.fmt_modifier, self.break_by,
                self.min_w, self.max_w)

    __slots__ = 'fmt', 'columns'

    def __init__(self, fmt):
        self.fmt = fmt or ""  # the original 'fmt' string
        self.columns = self._parse_cols_fmt(fmt)

    def verify_not_enhanced(self):
        """Raises exception if fmt contains any columns with value_path."""
        if self.columns in ["", "*"]:
            return

        cols_with_path = [col for col in self.columns if col.value_path is not None]
        if cols_with_path:
            descr = ", ".join(
                f"'{col.field_name}' <- '{col.value_path}'"
                for col in cols_with_path)
            raise ValueError(
                f"'value_path' description can only be used in enhanced fmt and "
                f"is not applicable for usual fmt. fmt of following columns "
                f"have 'value_path' description: {descr}")

    def cols_are_explicit(self) -> bool:
        """Check if fmt contains explicit columns list (not a special value)."""
        return self.columns not in ["", "*"]

    def _parse_cols_fmt(self, fmt_s_cols):
        # constructor helper: parse 'columns' part of the fmt string
        if fmt_s_cols in ("", "*"):
            return fmt_s_cols  # special values "change nothing" and "show all"

        return [self._parse_col_fmt(s) for s in fmt_s_cols.split(',')]

    @classmethod
    def _parse_col_fmt(cls, fmt):
        # constructor helper: parse a single column fmt descr.
        # "c_name!<-1.account.[c_name]:3-10" -> _ParsedColFmt
        result = cls._ParsedColFmt()
        result.fmt = fmt

        # 1.1. find field name
        chunks = [s.strip() for s in fmt.split(":")]
        if len(chunks) > 2:
            raise ValueError(
                f"Invalid column format (':' encontered more than once): '{fmt}'")
        elif len(chunks) == 2:
            # fmt looks like "name:5-15<-value_path"
            field_name, width_fmt = chunks
        else:
            # fmt is just a field name
            field_name = chunks[0]
            width_fmt = ""

        # detect presense of 'value_path'
        i = field_name.find('<-')
        if i != -1:
            result.value_path = field_name[i+2:].strip()
            field_name = field_name[:i].strip()

        # detect 'break_by' indicator
        result.break_by = field_name.endswith('!')
        if result.break_by:
            field_name = field_name[:-1]

        # detect optional format modifier
        i = field_name.find('/')
        if i >= 0:
            # field name includes format modifier. Like this: "user_uuid/short"
            result.fmt_modifier = field_name[i+1:]
            field_name = field_name[:i]

        result.field_name = field_name

        # 1.2. parse width limits
        # It may be either a number or range
        if width_fmt == '-1':
            # special value: column object will not be created from it
            result.min_w = -1
            result.max_w = -1
        elif width_fmt:
            chunks = width_fmt.split('-')
            if len(chunks) > 2:
                raise ValueError(f"Invalid width range: '{width_fmt}'")
            widths = []
            for w in chunks:
                try:
                    widths.append(int(w))
                except ValueError as err:
                    raise ValueError(
                        f"Invalid column fmt '{fmt}' specified for field "
                        f"'{field_name}': Invalid width '{w}'."
                    ) from err
            if len(widths) == 2:
                result.min_w, result.max_w = widths
            else:
                result.min_w = widths[0]
                result.max_w = result.min_w

        return result

    def get_fields_info(self):
        """Get field-specific information from columns descriptions.

        This method verifies that columns descriptions contain consistent
        fields-related information for all fields.

        Method returns {field_name: value_path_str}
        """
        path_by_field_name = {}
        fieldnames_wo_value_path = set()
        for col in self.columns:
            if col.value_path is None:
                # this column descr contains no value_path, but may be it is
                # included into another column referring to the same field
                fieldnames_wo_value_path.add(col.field_name)
                continue

            if col.field_name in path_by_field_name:
                prev_path = path_by_field_name[col.field_name]
                if prev_path == col.value_path:
                    # two columns contain value_paths for the same field.
                    # But these value_paths are the same - ok
                    continue
                raise ValueError(
                    f"fmt string contains different value_paths for the "
                    f"same field '{col.field_name}': '{prev_path}' and "
                    f"'{col.value_path}'. Original fmt string:\n{self.fmt}")

            path_by_field_name[col.field_name] = col.value_path

        return path_by_field_name


class ReprStructure:
    """Record structure and columns of a record's representation.

    The main purpose of this class is to process the 'fmt' string - description
    of the columns of a record's representation. Often sufficient information about
    the record structure can also be fetched from the 'fmt', so it is not necessary
    to specify construct RecordStructure explicitely.

    The 'fmt' string is a comma-separated string of individual columns descriptions.

    Example of a single column description:

        "c_name!<-1.account.[name_key]:3-10"

    In this example:
    - "c_name" : name of the field
    - "!" : (optional) 'break_by' indicator
    - "<-1.account.[name_key]" : (optional) path to the location of the corresponding
      value in a record object. In this case the path means:
        value = record_obj[1].account['name_key']
    - ":3-10" : (optional) minimum and maximum width of the column.
        ":n-n" is equivalent to a shorter ":n"
    """
    __slots__ = (
        'record_structure',
        'columns',
        'title_field_type',
        'borders',
        '_repr_style',
    )

    _DFLT_FIELD_TYPE = _DefaultFieldType()
    _DFLT_TITLE_FIELD_TYPE = _DefaultTitleFieldType()
    _DFLT_REPR_STYLE = RecordReprStyle()

    def __init__(self, record_structure, columns, borders, style=None):
        self.record_structure: RecordStructure = record_structure
        self.columns: [ReprColumn] = columns
        self.title_field_type = self._DFLT_TITLE_FIELD_TYPE
        self._repr_style = style or self._DFLT_REPR_STYLE
        self.borders = borders
        assert len(self.borders) == len(self.columns) + 1, (
            f"{self.borders}, {self.columns}")

    def clone(self):
        return ReprStructure(
            self.record_structure, # it is immutable, no need to clone
            [c.clone() for c in self.columns],
            self.borders,
            self._repr_style,
        )

    @classmethod
    def make(
        cls, fmt, fields, fields_types, fields_titles, sample_record,
        style=None,
    ):
        """Alternative constructor of ReprStructure.

        Arguments:
        - fmt: format string, describes columns of the table. Check ReprStructure
            doc to get the description of the format of this string.
        - fields: [RecordField|str], describes record structure, that is location
            of field values in the record object.
        - fields_types: {field_name: FieldType}. Optional.
        - fields_titles: {field_name: title_items}. Optional. The title_items may be:
            - simple string
            - string containing new-line characters (for multi-line title)
            - list of strings or other simple objects (for multi-line title)
        - sample_record: (optional) sample record.
        - style: optional instance of RecordReprStyle class. Contains some parameters
            which affect the format of the record (such as what symbols to use for
            borders)

        All the arguments are optional, the method fetches information about record
        structure and report columns from whatever is provided.
        """
        style = style or cls._DFLT_REPR_STYLE
        parsed_fmt = cls._parse_fmt(fmt)
        fields_types_dict = {} if fields_types is None else fields_types
        fields_titles_dict = {} if fields_titles is None else fields_titles

        record_structure = None
        repr_columns = None

        if fields is not None:
            # information about RecordStructure is specified explicitely.
            #
            # We expect records to be tuples, rec[i] corresponds to a fields[i] field
            assert isinstance(fields, (list, tuple))
            def _local_mk_rec_fld(pos, obj):
                if isinstance(obj, RecordField):
                    return obj
                assert isinstance(obj, str), (
                    f"unexpected value of type {type(obj)} in the 'fields' list. "
                    f"Expected RecordField or str")
                f_name = obj
                return RecordField(
                    f_name,
                    fields_types_dict.get(f_name, cls._DFLT_FIELD_TYPE),
                    pos, fields_titles_dict.get(f_name))
            record_structure = RecordStructure([
                _local_mk_rec_fld(pos, obj)
                for (pos, obj) in enumerate(fields)])

        if record_structure is None and hasattr(sample_record, '_fields'):
            # we can get RecordStructure from the sample record
            record_structure = RecordStructure([
                RecordField(
                    name,
                    fields_types_dict.get(name, cls._DFLT_FIELD_TYPE),
                    pos, fields_titles_dict.get(name))
                for pos, name in enumerate(sample_record._fields)])

        if record_structure is not None:
            # as the record structure is specified explicitely, the position of
            # fields must not be specified in the 'fmt'
            parsed_fmt.verify_not_enhanced()

        if parsed_fmt.cols_are_explicit():
            if record_structure is None:
                # try to fetch fields positions from the 'fmt' argument.
                # The problem here is that the 'fmt' describes representation
                # columns, not record fields. Multiple columns may refer to the
                # same field, will need to detect conflicts.
                #
                # The only field-related information in the 'fmt' is the value path.
                # Possible conflicts will be detected here:
                value_path_by_field = parsed_fmt.get_fields_info()
                fields_list = []
                processed_fields_names = set()
                for c in parsed_fmt.columns:
                    if c.field_name in processed_fields_names:
                        continue
                    processed_fields_names.add(c.field_name)
                    fields_list.append(RecordField(
                        c.field_name,
                        fields_types_dict.get(c.field_name, cls._DFLT_FIELD_TYPE),
                        value_path_by_field.get(
                            c.field_name,
                            c.field_name,  # if path to the field is not specified we
                                           # interprete it as
                                           # 'the field name itself is the path'
                        ),
                        fields_titles_dict.get(c.field_name),
                    ))
                record_structure = RecordStructure(fields_list)
            repr_columns = [
                c.mk_repr_column(record_structure.get_field(c.field_name))
                for c in parsed_fmt.columns
                # nagative width specified in the 'fmt' indicates that the field
                # exists and it is possible to change format to display it, but
                # right now the column for this field is not required.
                if c.max_w is None or c.max_w >= 0
            ]

        if record_structure is None and sample_record is not None:
            # the only information about record structure is the sample record.
            # and the sample record does not have explicit fields list.
            if not isinstance(sample_record, (list, tuple)):
                raise ValueError(
                    f"Can get record structure from a sample record only if the "
                    f"sample record is 'simple' (s a list or a tuple). Provided "
                    f"sample record is not 'simple': {type(sample_record)} "
                    f"{sample_record}. Provide record structure information "
                    f"using 'fields' argument")
            record_structure = RecordStructure([
                RecordField(f"col_{pos+1}", cls._DFLT_FIELD_TYPE, pos, None)
                for pos in range(len(sample_record))
            ])

        if record_structure is None:
            # There was no explicit information about record structure or columns.
            # The only reasonable situation when it can happen is when the report
            # was supposed to be built based on the sample record, but there are
            # no records. Still need to display some dummy table
            record_structure = RecordStructure([
                RecordField(
                    '-                              -', cls._DFLT_FIELD_TYPE,
                    0, None)
            ])

        if repr_columns is None:
            # we know the record sctructure, but list of columns was not specified.
            # by default show all the fields
            repr_columns = [ReprColumn(field) for field in record_structure.fields]

        borders = [style.inner_border for _ in range(len(repr_columns)-1)]
        borders.insert(0, style.left_border)
        borders.append(style.right_border)

        return cls(record_structure, repr_columns, borders, style)

    def col_widths_finalized(self) -> bool:
        """Check if actual widths of columns are already known."""
        return all(col.width is not None for col in self.columns)

    def detect_actual_columns_widths(
            self, body_records, *,
            _account_columns_names=True):
        """Calculate actual widths of columns using the actual records."""
        if _account_columns_names:
            for col in self.columns:
                title_width = col.get_title_width()
                col.width = min(col.max_width, max(col.min_width, title_width))
        else:
            for col in self.columns:
                col.width = col.min_width

        for rec in body_records:
            for col in self.columns:
                if col.width < col.max_width:
                    col.width = max(
                        col.width, min(col.max_width, col.get_cell_text_len(rec))
                    )
            if all(col.width == col.max_width for col in self.columns):
                break

    def get_borders_positions(self):
        """Returns {col_start_pos: text_of_left_border}."""
        borders_positions = {}
        assert self.col_widths_finalized()
        assert len(self.borders) == len(self.columns) + 1, (
            f"{self.borders=}, {self.columns=}")
        cur_pos = 0
        for column, border in zip(self.columns, self.borders):
            cur_pos += len(border)
            borders_positions[cur_pos] = border
            cur_pos += column.width
        return borders_positions

    def remove_columns(self, columns_names):
        """Remove specified column from self"""
        new_columns = []
        new_borders = [self.borders[0]]  # left outer border remains the same
        for i, col in enumerate(self.columns):
            if col.name not in columns_names:
                if new_columns:
                    # add left border of the column only of this is NOT the very
                    # first of remaining columns. The left border of the very
                    # first column is the outer record border
                    new_borders.append(self.borders[i])
                new_columns.append(col)
        new_borders.append(self.borders[-1])
        self.columns = new_columns
        self.borders = new_borders

    def make_record_ch_chunks_all(self, record, cp) -> [[CHText.Chunk]]:
        """Create intermediate data for the record's text representation.

        Returns [[CHText.Chunk]], where each inner list corresponds to a column
        in self.columns.
        """
        result = []
        for col in self.columns:
            result.append(col.make_cell_ch_chunks(record, cp))
        return result

    def make_title_line_ch_chunks_all(self, cols_titles, cp) -> [[CHText.Chunk]]:
        """Create intermediate data for record's title line representation.

        Title may consist of several lines. This method produces one line.

        Returns [[CHText.Chunk]], where each inner list corresponds to a current
        title line of a column in self.columns.
        """
        assert len(cols_titles) == len(self.columns)

        return [
            self.title_field_type.make_cell_ch_chunks(title, None, col.width, cp)
            for title, col in zip(cols_titles, self.columns)
        ]

    def gen_title_lines_values(self):
        """Generate lists of values which are titles of the ReprStructure columns.

        There may be more than one such list if the title is muli-line.
        Length on each list is equal to the number of columns.

        """
        num_title_lines = max(len(col.field.title_lines) for col in self.columns)
        for i in range(num_title_lines):
            yield [
                col.field.title_lines[i] if i < len(col.field.title_lines) else ""
                for col in self.columns]

    def __repr__(self):
        # it's important that repr contains fmt string, which can be used
        # to construct new format objects
        return self._get_fmt_str()

    def __str__(self):
        return self._get_fmt_str()

    def _get_fmt_str(self) -> str:
        # create the 'fmt' string which describes self.
        return ",".join(c.to_fmt_str() for c in self.columns)

    def _set_parsed_fmt(self, parsed_fmt, other=None):

        assert isinstance(parsed_fmt, _ColumnsParsedFmt)
        fields_by_name = {f.name: f for f in self.record_structure.fields}

        # 1. create list of columns
        columns = []
        if parsed_fmt.columns == "" and other is not None:
            # copy columns from the other
            columns = [c.clone() for c in other.columns]
        elif parsed_fmt.columns in ("", "*"):
            # show column for each field
            for field in self.record_structure.fields:
                columns.append(ReprColumn(
                    field,
                    None,  # fmt_modifier
                    False,  # break_ty
                    field.field_type.min_width, field.field_type.max_width))
        else:
            # columns specified in the fmt
            for c in parsed_fmt.columns:
                if c.field_name not in fields_by_name:
                    avail_fields = ", ".join(fields_by_name.keys())
                    raise ValueError(
                        f"column fmt '{c.fmt}' refers to unknown field "
                        f"'{c.field_name}'. Available fields: {avail_fields}")
                field = fields_by_name[c.field_name]

                if all(w is not None and w < 0 for w in [c.min_w, c.max_w]):
                    # special case: column description was used to create
                    # field only, column will not be created for it
                    assert c.min_w == -1 and c.max_w == -1
                    continue

                columns.append(ReprColumn(
                    field,
                    c.fmt_modifier, c.break_by,
                    c.min_w, c.max_w))

        self.columns = columns

        # as of now info about borders is not implemented in fmt.
        # make the default borders
        self.borders = [
            self._repr_style.inner_border for _ in range(len(self.columns)-1)]
        self.borders.insert(0, self._repr_style.left_border)
        self.borders.append(self._repr_style.right_border)

    @staticmethod
    def _parse_fmt(fmt) -> _ColumnsParsedFmt:
        # parse fmt string if not parsed yet
        if isinstance(fmt, _ColumnsParsedFmt):
            return fmt
        if fmt is None:
            fmt = ""
        assert isinstance(fmt, str), f"{type(fmt)}: {fmt}"
        return _ColumnsParsedFmt(fmt)


#########################
# PPRecord

class PPRecordFmt(PaletteUser):
    """Object of this class prints records in specified format."""

    class PPRecordPalette(CompoundPalette, FieldType.RecordPalette):
        SUB_PALETTES_MAP = {}
        SYNTAX_DEFAULTS = {
            'RECORD.WARN': "WARN",
            'RECORD.BORDER': "GREEN",
        }

        warn = ConfColor('RECORD.WARN')
        border = ConfColor('RECORD.BORDER')

    PALETTE_CLASS = PPRecordPalette

    Style = RecordReprStyle
    _DFLT_STYLE = ReprStructure._DFLT_REPR_STYLE

    def __init__(
        self, fmt, *,
        fields=None, fields_types=None, fields_titles=None, sample_record=None,
        style=None,
        repr_structure=None,
        palette=None, no_color=None, compound_palette=None, shade_name=None,
    ):
        """ PPRecordFmt constructor.

        - fmt, fields, fields_types, fields_titles, sample_record, style: arguments
            required to construct ReprStructure: object which contains information
            about record fields and representation columns. Check ReprStructure
            doc for more detailed description.
        - repr_structure: optional ReprStructure object, can be specified instead of
            all the previous arguments.
        - palette, no_color, compound_palette, shade_name: set of arguments which
            specify default palette used for formatting records. Check PPObj.ch_text
            doc string for detailed description of these arguments.
            The palette information may be overriden later by calling 'set_palette'
            method, or it may be specified for a single format record call.
        """
        if repr_structure is None:
            repr_structure = ReprStructure.make(
                fmt, fields, fields_types, fields_titles, sample_record,
                style=style or self._DFLT_STYLE,
            )
        else:
            assert fmt is None
            assert fields is None
            assert fields_types is None
            assert fields_titles is None
            assert sample_record is None
            assert style is None

        self.repr_structure = repr_structure

        self._cp = None
        self._borders = None
        self.set_palette(
            palette=palette,
            no_color=no_color,
            compound_palette=compound_palette,
            shade_name=shade_name,
        )

    def remove_columns(self, columns_names):
        """Remove columns from the record formatter."""
        self.repr_structure.remove_columns(columns_names)
        self._borders = self._make_borders_chtext(self._cp)

    def set_palette(
        self, palette=None, no_color=None, compound_palette=None, shade_name=None,
    ):
        """Set palette for this Record Formatter.

        It is possible to specify all the palette-related information with
        each call of the formatter.
        Instead it is possible to specify it once.
        It may be more convenient and is slightly more efficient.
        """
        self._cp = self._mk_palette(palette, no_color, compound_palette, shade_name)
        self._borders = self._make_borders_chtext(self._cp)

    def __call__(
        self, record=None, *, palette=None, no_color=None,
        compound_palette=None, shade_name=None, **kwargs,
    ) -> CHText:
        """Create colored text representation of the record.

        Arguments:
        - record: object to print. If the object to print is a simple dictionary it
            is possible to use kwargs instead.
        - palette, no_color, compound_palette, shade_name: arguments which identify
            color palette to be used. Check PPObj.ch_text doc for detailed
            description of these arguments.
            It is more efficient to specify these arguments not for each call but
            once (either in the constructor or in 'set_palette' method)
        - kwargs: alternative way to specify the object to print.
        """
        if kwargs:
            assert record is None, (
                f"both 'record' and keyword arguments are specified specified: "
                f"{record=}; {kwargs=}")
            record = kwargs

        if not self.repr_structure.col_widths_finalized():
            self.repr_structure.detect_actual_columns_widths(
                [record],
                _account_columns_names=False,
            )

        cp, borders = self._mk_cp_and_chborders(
            palette, no_color, compound_palette, shade_name)

        return self._compose_line_with_borders(
            self.repr_structure.make_record_ch_chunks_all(record, cp),
            borders)

    def _mk_cp_and_chborders(self, palette, no_color, compound_palette, shade_name):
        # Text of borders between fields does not depend on palette.
        # But the colored text of the borders does.
        # This method chooses palette and ceates corresponding chtext for borders
        if (
            palette is None and no_color is None
            and compound_palette is None and shade_name is None
        ):
            return self._cp, self._borders

        cp = self._mk_palette(palette, no_color, compound_palette, shade_name)
        return cp, self._make_borders_chtext(cp)

    def _make_title_line(self, cols_titles, chborders, cp) -> CHText:
        # returns CHText corresponding to a single line of the title
        return self._compose_line_with_borders(
            self.repr_structure.make_title_line_ch_chunks_all(cols_titles, cp),
            chborders)

    @staticmethod
    def _compose_line_with_borders(ch_chunks_all, chborders) -> CHText:
        # compose CHText chunks corresponding to fields with CHText chunks
        # corresponding to borders to produce a CHText for the whole record
        assert len(chborders) == (len(ch_chunks_all) + 1) if ch_chunks_all else 2, (
            f"{len(ch_chunks_all)=}, {len(chborders)=}")

        result_chunks = []
        for border, ch_items in zip(
            chborders, ch_chunks_all
        ):
            result_chunks.append(border)
            result_chunks.extend(ch_items)
        if len(result_chunks) == 0:
            # there are no columns in this record representation.
            # still need to include left outer border into output
            result_chunks.append(chborders[0])
        result_chunks.append(chborders[-1])

        return CHText.make(result_chunks)

    def title(
        self, palette=None, no_color=None,
        compound_palette=None, shade_name=None,
    ) -> CHTextResult:
        """Produce title lines.

        The result is a CHTextResult object, so it can be used either as a
        single CHText or an iterator of CHText objects corresponding to the
        individual title lines.

        Arguments:
        - palette, no_color, compound_palette, shade_name: arguments which identify
            color palette to be used. Check PPObj.ch_text doc for detailed
            description of these arguments.
            There is no need to specify these arguments if this palette-related
            information was specified previously (either in constructor or
            uging 'set_palette' method)
        """
        cp, chborders = self._mk_cp_and_chborders(
            palette, no_color, compound_palette, shade_name)

        if not self.repr_structure.col_widths_finalized():
            self.repr_structure.detect_actual_columns_widths(
                [], _account_columns_names=True)

        return CHTextFixedListResult([
            self._make_title_line(tl, chborders, cp)
            for tl in self.repr_structure.gen_title_lines_values()
        ])

    def make_summary_fmt(self, **summary_columns):
        """Create PPRecordFmt for printing summary records.

        Positions of columns of the result PPRecordFmt are calculated based on
        position of columns of self.

        Arguments:
        - summary_columns: description of the columns in the result PPRecordFmt.
            Each value may be:
            - src_column_name (*)
            - (src_column_name, FieldType) (**)

        (*) src_column_name may be:
        - None: indicates the very first column which is supposed to contain
            text description of the summary record. This description column
            does not correspond to any column in self
        - "col_name": name of the corresponding column in self. The start position
            of these columns on screen will be the same.
        - "col_name|": '|' suffix indicates that not only the start postion but
            also the end position of corresponding columns will be the same

        Result PPRecordFmt expects records which are simple dictionaries, with
        keys the same as keys of summary_columns argument.
        """

        # 1. analize position of own columns
        own_cols_positions = {} # {column_name: (start_pos, end_pos)}
        own_cols_fields_types = {}
        cur_col_start_pos = 0
        all_fields_names = {
            f.name for f in self.repr_structure.record_structure.fields}
        for c in self.repr_structure.columns:
            width = c.width if c.width is not None else c.min_width
            next_col_start_pos = cur_col_start_pos + width + 1 # 1 is for delimiter
            own_cols_positions[c.name] = (cur_col_start_pos, next_col_start_pos)
            cur_col_start_pos = next_col_start_pos
            own_cols_fields_types[c.name] = c.field.field_type

        own_last_col_end_pos = cur_col_start_pos

        # 2. analize arguments

        summ_columns_data = [] # [[name, start_pos, end_pos, type], ]

        for summ_col_name, summ_col_params in summary_columns.items():
            if isinstance(summ_col_params, (list, tuple)):
                assert len(summ_col_params) == 2, (
                    f"Unexpected format of the summary column '{summ_col_name}'. "
                    f"Expected a tuple ('orig_column_name', field_type): "
                    f"{summ_col_params}")
                src_col_name, field_type = summ_col_params
            else:
                src_col_name, field_type = summ_col_params, None

            end_pos_fixed = False
            if src_col_name is not None:
                if src_col_name.startswith('|'):
                    src_col_name = src_col_name[1:]
                if src_col_name.endswith('|'):
                    src_col_name = src_col_name[:-1]
                    end_pos_fixed = True

            src_col_pos = own_cols_positions.get(src_col_name)
            if src_col_pos is None:
                if src_col_name is None:
                    # special case, very first summary column not corresponding to
                    # any src column
                    start_pos = 0
                    end_pos = None
                else:
                    if src_col_name in all_fields_names:
                        # the column name is valid, just column is invisible
                        continue
                    raise ValueError(
                        f"Can't create summary record formater. "
                        f"Unexpected column name '{src_col_name}' specified.")
            else:
                start_pos, end_pos = src_col_pos

            if field_type is None:
                # field_type was not specified explicitely. Try to use the type
                # of the corresponding own field
                field_type = own_cols_fields_types.get(src_col_name)

            if not end_pos_fixed:
                end_pos = None

            summ_columns_data.append(
                [summ_col_name, start_pos, end_pos, field_type])

        summ_columns_data.sort(key=lambda x: x[1]) # sort by start_pos
        next_col_start_pos = own_last_col_end_pos
        for col_data in reversed(summ_columns_data):
            if col_data[2] is None:
                # end position of the column is not fixed, extend it to the next col
                col_data[2] = next_col_start_pos
            next_col_start_pos = col_data[1]

        # start and end positions of all the columns are ready.
        # But there may be gaps between them. Let's insert dummy filler columns
        full_summ_colums_data = []
        last_col_end_pos = 0
        for col_data in summ_columns_data:
            if col_data[1] != last_col_end_pos:
                # gap between columns detected
                assert col_data[1] > last_col_end_pos
                filler_col_data = [None, last_col_end_pos, col_data[1], None]
                full_summ_colums_data.append(filler_col_data)
            full_summ_colums_data.append(col_data)
            last_col_end_pos = col_data[2]

        summ_columns_data = full_summ_colums_data

        # ready to prepare RecordField objects
        own_borders_positions = self.repr_structure.get_borders_positions()
        cur_filler_col_id = 0
        fields = []  # [RecordField, ]
        columns = []  # [ReprColumn, ]
        borders = []
        for name, start_pos, end_pos, field_type in summ_columns_data:
            if name is None:
                # this is a filler column
                name = f"__filler_{cur_filler_col_id}"
                cur_filler_col_id += 1
                value_path = "="  # constant empty string
            else:
                value_path = f"[{name}]"

            if field_type is None:
                field_type = ReprStructure._DFLT_FIELD_TYPE

            width = end_pos - start_pos - 1
            field = RecordField(name, field_type, value_path, name)
            column = ReprColumn(field, min_width=width, max_width=width)
            fields.append(field)
            columns.append(column)
            borders.append(own_borders_positions.get(start_pos, ""))
        borders.append(self.repr_structure.borders[-1])

        record_structure = RecordStructure(fields)
        repr_structure = ReprStructure(
            record_structure, columns,
            borders, self.repr_structure._repr_style,
        )

        return PPRecordFmt(None, repr_structure=repr_structure)

    def _make_borders_chtext(self, cp) -> [CHText.Chunk]:
        # prepare text of borders between fields
        return [
            cp.border(border_text) for border_text in self.repr_structure.borders]


#########################
# PPTable

@dataclass(frozen=True)
class TableStyle:
    """Table style.

    Specifies whether to print borders, titles, etc.
    Does NOT contain coloring information.
    """
    inner_border: str = "|"
    left_border: str = "|"
    right_border: str = "|"
    horiz_border: str = "-"

    show_column_titles: bool = True
    show_horiz_borders: bool = True
    table_name_style: str = "std"
    show_summary_line: bool = True


class PPTable(PPObj):
    """2-D table.

    Provides pretty-printing and simple manipulation on 2-D table
    of data (such as results of sql query).
    """

    class TablePalette(CompoundPalette):
        """Palette to be used to print PPTable."""
        SYNTAX_DEFAULTS = {
            # synt_id: default_color
            'TABLE.BORDER': "GREEN",
            'TABLE.WARN': "WARN",
            'TABLE.HEADER': "GREEN:bold",
        }

        SUB_PALETTES_MAP = {}

        border = ConfColor('TABLE.BORDER')
        warn = ConfColor('TABLE.WARN')
        header = ConfColor('TABLE.HEADER')

    PALETTE_CLASS = TablePalette

    Style = TableStyle

    _DFLT_STYLE = TableStyle()

    class _ServiceLine:
        # contents of a 'service' line of a printed table - line, which
        # doesn't correspond to any record (f.e. empty 'break by' line)
        __slots__ = ('ch_text', )
        def __init__(self, ch_text=None):
            self.ch_text = ch_text

    def __init__(
            self, records, *,
            header=None,
            footer=None,
            fmt=None,
            fmt_obj=None,
            limits=None,
            skip_columns=None,
            fields=None,
            fields_types=None,
            fields_titles=None,
            style=None,
    ):
        """Constructor of PPTable object - this object prints table.

        Some terminology:
        - column: visible column in a table
        - field: possible source of values for the column; describs how to get a
            value from record object and possible ways to format it

        Arguments:
        - records: list of objects, containig data for table rows. All the
            objects must have similar structure (it may be a simple list or
            tuple of values or something more complex)
        - header, footer: (optional) text for header and footer of the table
        - fmt: (optional) string, describing columns of the table. Check
            PPTableFormat doc for more details.
        - fmt_obj: (optional) PPTableFormat object
        - limits: override default or specified in fmt numbers of printable records.
            Acceptable values:
            - None: ignored (default number of records will be printed)
            - (n_first, n_last) - tuple of two optional integers
        - skip_columns: list of columns to skip. Overrides fmt argument.
        - fields: (optional) list of names of fileds in a record, or list
            of RecordField objects
        - fields_titles: optional {field_name: title_items}. The title_items may be:
            - simple string
            - string containing new-line characters (for multi-line title)
            - list of strings or other simple objects (for multi-line title)
        - fields_types: (optional) dictionary {field_name: FieldType}.
        - style: optional PPTable.Style object which affects table look: characters
            to be used as borders, whether to print summary, etc.

        Combinations of arguments used in common scenarios:

        PPTable(
            records,
            fmt="field_a, field_b",  # names of fields for visible columns
            fields=["field_1", ...],  # correspondence of fields to values in record
            fields_types={...}, # FieldType for those fields, for which
                                # default field type does not work
        )

        PPTable(
            records,
            fmt="field_a<-value_path, ...",  # to be used if records have
                                             # complex structure
            fields_types={...},
        )

        (value_path example: "zipcode<-0.[user].address."
        - 0 - means position in a list/tuple
        - address - sttribute name
        - [user] - in square brakets, means 'user' is a key in a dictionary
        - . - skipped last element, means the last element is the same as field name
            (in this case 'zipcode')
        )

        Check doc of PPTableFormat for more detailed description of fmt string.
        """
        self.records = records
        # each PPObj should have 'r' attribute, which contains 'original' object.
        # In case of table the original object is the list of records:
        self.r = self.records

        if fmt_obj is not None:
            assert fields is None
            assert fields_types is None
            assert fmt is None
            assert fields_titles is None
            assert style is None
            self._ppt_fmt = fmt_obj.clone()
        else:
            self._ppt_fmt = PPTableFormat.make(
            fmt, fields, fields_types, fields_titles,
            self.records[0] if self.records else None,
            style=style or self._DFLT_STYLE)

        self._ppt_fmt.set_limits(limits)

        if skip_columns is not None:
            self._ppt_fmt.remove_columns(skip_columns)

        self.header = header
        self.footer = (
            footer if footer is not None else f"Total {len(self.records)} records")

    def set_fmt(self, fmt):
        """Specify fmt - a string which describes format of the table.

        Method returns self - so that in python console the modified table be
        printed out immediately.
        """
        new_fmt_obj = self._ppt_fmt.clone()
        parsed_fmt = PPTableFormat._parse_fmt(fmt)
        new_fmt_obj._set_parsed_fmt(parsed_fmt, self._ppt_fmt)
        self._ppt_fmt = new_fmt_obj
        return self

    def _get_fmt(self):
        # getter of 'fmt' property.
        # returns PPTableFormat object
        # repr of this object contains fmt string which can be used to apply
        # new format
        return self._ppt_fmt

    fmt = property(_get_fmt, set_fmt)

    def remove_columns(self, columns_names):
        """Remove columns from table.

        Arguments:
        - columns_names: list of names of columns to remove. (values not
            equal to name of any column are accepted but ignored).
        """
        self._ppt_fmt.remove_columns(columns_names)

    def gen_ch_lines(self, cp: Palette) -> Iterator[CHText]:
        """Generate CHText objects - lines of the printed table"""

        repr_structure = self._ppt_fmt.repr_structure
        columns = repr_structure.columns
        style = self._ppt_fmt.style

        # prepare list of table lines. Table line may correspond to a record
        # or to a special markup lines
        table_lines = []
        break_line = self._ServiceLine()
        skipped_recs_line = self._ServiceLine()
        break_by_fields = [col.field for col in columns if col.break_by]
        prev_break_by_values = None
        for rec in self.records:
            cur_break_by_values = [
                field.fetch_value(rec) for field in break_by_fields]
            if (prev_break_by_values is not None and
                prev_break_by_values != cur_break_by_values
            ):
                table_lines.append(break_line)
            table_lines.append(rec)
            prev_break_by_values = cur_break_by_values

        # check if some records should be hidden because of record numbers limits
        n_first = self._ppt_fmt.limit_flines
        n_last = self._ppt_fmt.limit_llines
        if (n_first is not None
            and n_last is not None
            and len(table_lines) > n_first + n_last + 1
           ):
            first_lines = table_lines[:n_first] if n_first else []
            last_lines = table_lines[-n_last:] if n_last else []
            # calculate number of not visible records.
            n_skipped = len(self.records) - sum(
                1 if not isinstance(tl, self._ServiceLine) else 0
                for tlines in (first_lines, last_lines)
                for tl in tlines)
            table_lines = first_lines + [skipped_recs_line] + last_lines
        else:
            # show all records
            n_skipped = 0
        self._ppt_fmt.any_lines_skipped = n_skipped > 0

        # calculate actual widths of table columns (col.width)
        if not repr_structure.col_widths_finalized():
            repr_structure.detect_actual_columns_widths(
                (
                    rec for rec in table_lines
                    if not isinstance(rec, self._ServiceLine)
                )
            )

        # there is no need to specify style when constructing PPRecordFmt
        # because the record-related style information is present in
        # the repr_structure
        normal_line_fmt = PPRecordFmt(
            None, repr_structure=repr_structure, palette=cp)

        table_width = (
            sum(col.width for col in columns)
            + sum(len(b) for b in repr_structure.borders)
        )

        # contents of service lines can be created now
        inner_width = (table_width
            - len(repr_structure.borders[0]) - len(repr_structure.borders[-1]))
        left_ch_brd = cp.border(repr_structure.borders[0])
        right_ch_brd = cp.border(repr_structure.borders[-1])
        break_line.ch_text = CHText(
            cp.border(repr_structure.borders[0]),
            " "*inner_width,
            cp.border(repr_structure.borders[-1]),
        )
        skipped_line_contents = FieldType.fit_to_width(
            [
                cp.warn("... "),
                cp.text(f"{n_skipped} records skipped"),
            ],
            inner_width,
            FieldType.ALIGN_LEFT,
            cp)
        skipped_line_contents.insert(0, left_ch_brd)
        skipped_line_contents.append(right_ch_brd)
        skipped_recs_line.ch_text = CHText.make(skipped_line_contents)

        # 1. make first border line
        border_line = None
        if style.show_horiz_borders:
            border_line = self._make_separator_line(cp)

        if border_line is not None:
            yield border_line

        # 2. table header (name)
        if self.header:
            line = FieldType.fit_to_width(
                [cp.header(self.header)], inner_width, FieldType.ALIGN_LEFT, cp)
            line.insert(0, left_ch_brd)
            line.append(right_ch_brd)
            yield CHText.make(line)

        # 3. multi column titles
        if style.show_column_titles:
            yield from normal_line_fmt.title()

        # 4. one more border_line
        if (self.header or style.show_column_titles) and border_line is not None:
            yield border_line

        # 5. table contents - actual records and service lines
        for tl in table_lines:
            if isinstance(tl, self._ServiceLine):
                yield tl.ch_text
            else:
                yield normal_line_fmt(tl)

        # 6. final border line
        if border_line is not None:
            yield border_line

        # 7. summary line
        if style.show_summary_line and self.footer:
            yield CHText.make(FieldType.fit_to_width(
                [cp.text(self.footer)], table_width, FieldType.ALIGN_LEFT, cp))

    def _make_separator_line(self, cp: Palette) -> CHText:
        # create horizontal border line

        repr_structure = self._ppt_fmt.repr_structure
        # it the horiz_border character is '-' the line will look like "+-----+--+"
        ch = self._ppt_fmt.style.horiz_border or " "
        s_ch = '+' if ch == '-' else ch
        first_ch = '+' if ch == '-' else repr_structure.borders[0]
        last_ch = '+' if ch == '-' else repr_structure.borders[-1]

        line_chunks = []
        for border, column in zip(repr_structure.borders, repr_structure.columns):
            if len(line_chunks) == 0:
                # the very first border
                line_chunks.append(first_ch*len(border))
            else:
                line_chunks.append(s_ch*len(border))
            line_chunks.append(ch*column.width)
        if len(line_chunks) == 0:
            # there are no columns in this record representation.
            # still need to include left outer border into output
            line_chunks.append(first_ch*len(repr_structure.borders[0]))

        # right border
        line_chunks.append(last_ch*len(repr_structure.borders[-1]))
        return cp.border("".join(line_chunks))


class _PPTableParsedFmt:
    # parser of fmt - string representing PPTable format

    __slots__ = ('fmt', 'cols_parsed_fmt', 'vis_lines', 'table_width')

    def __init__(self, fmt):
        """Parse fmt - string containing PPTable format description"""
        self.fmt = fmt

        if fmt is None:
            fmt = ";;"

        # fmt is "visible_columns ; visible_records ; table_width"
        fmt_s_cols, fmt_s_lines, _fmt_s_twidths = self._fmt_str_split(fmt)

        self.cols_parsed_fmt = _ColumnsParsedFmt(fmt_s_cols)

        self.vis_lines = self._parse_vis_lines_fmt(fmt_s_lines)
        self.table_width = None  # not implememnted

    @staticmethod
    def _fmt_str_split(fmt_str):
        # constructor helper: split 'fmt' string into 3 sections
        if fmt_str is None:
            fmt_str = ";;"
        parts = fmt_str.split(';')
        if len(parts) > 3:
            raise ValueError(
                f"Invalid fmt string (it contains more than 3 "
                f" ';'-delimited sections: '{fmt_str}'")

        while len(parts) < 3:
            parts.append("")  # "" format means "no need to change anything"

        return parts

    @staticmethod
    def _parse_vis_lines_fmt(fmt_s_lines):
        # constructor helper: parse 'visible lines' part of fmt string
        if fmt_s_lines == "":
            return None
        if fmt_s_lines == "*":
            return (None, None)

        # "20:10" - show 20 first recs and 15 last recs
        parts = [x.strip() for x in fmt_s_lines.split(':')]
        if len(parts) != 2:
            raise ValueError(
                f"Invalid visible lines limits fmt: '{fmt_s_lines}'. "
                f"If limits are specified, they should be in form "
                f"'max_num_first_lines:max_num_last_lines'")
        try:
            n_first, n_last = [int(x) for x in parts]
        except ValueError as err:
            raise ValueError(
                f"Invalid visible lines limits fmt: '{fmt_s_lines}'"
            ) from err

        return n_first, n_last


class PPTableFormat:
    """Contains information about PPTable format: visible columns, etc.

    PPTableFormat can be described by string (so called 'fmt' string),
    and can be constructed based on fmt string.

    'fmt' string consists of 3 parts separated by ';'. These parts are
    1. visible columns descriptions
    2. record limits description
    3. total table width (not implemented)

    Special values for each part are:
    "" - keep format as in 'other' or create default
    "*" - "show all"

    1. visible columns description describes columns of the table. Examples:

        "field_1:7, field_2:5-20" - two columns, width of first is fixed, width
          of the second must be in range [5-20].

        "field_1!:7" - '!' indicates 'break_by' property: empty line will be
          inserted into table whenever value of this column changes.

        "field_1!<-0.attr" - '<-0.attr' specifies 'value_path' - property
          required in some scenarios of PPTable creation when information
          about fields is included into columns descriptions.

    2. record limits example:

        "10:15" - if number of records is more that 26, only 10 first and
          15 last records will be displayed.

    3. not implemented.
    """

    _DFLT_LIMIT_LINES = (30, 20)  # n_first, n_last

    def __init__(self, repr_structure, style, limit_flines=None, limit_llines=None):
        """Constructor of PPTableFormat.

        Arguments:
        - repr_structure: ReprStructure, contains information about columns
        - limit_flines, limit_llines - limits of numbers of visible lines

        Alternative constructor is the 'make' method.
        """
        assert isinstance(repr_structure, ReprStructure)
        self.repr_structure = repr_structure  # ReprStructure
        self.style = style
        self.limit_flines = limit_flines
        self.limit_llines = limit_llines
        # indicates if the table (which ownes this format object) has more lines
        # than can be displayed (because of self.limit_flines and self.limit_llines
        # limits)
        self.any_lines_skipped = None

    @classmethod
    def make(
        cls, fmt, fields, fields_types, fields_titles,
        sample_record=None, style=PPTable._DFLT_STYLE,
    ):
        """Alternative PPTableFormat constructor.

        Arguments:
          Check ReprStructure.make doc string for detailed description of arguments.
        """
        parsed_fmt = PPTableFormat._parse_fmt(fmt)
        limit_flines, limit_llines = parsed_fmt.vis_lines or (None, None)

        return PPTableFormat(
            ReprStructure.make(
                parsed_fmt.cols_parsed_fmt,
                fields, fields_types, fields_titles, sample_record, style),
            style, limit_flines, limit_llines,
        )

    def clone(self):
        return PPTableFormat(
            self.repr_structure.clone(), self.style,
            self.limit_flines, self.limit_llines)

    def remove_columns(self, columns_names):
        """Remove columns from table."""
        self.repr_structure.remove_columns(columns_names)

    def set_limits(self, limits):
        """Change number of printrable records.

        Possible values:
        - None: leave the limits as is
        - (n_first, n_last): tuple of two optional integers
        """
        if limits is None:
            return
        assert isinstance(limits, (list, tuple)) and len(limits) == 2, (
            f"invalid limits specified: {limits}. Expected value is None "
            f"or (n_firts, n_last)")
        self.limit_flines, self.limit_llines = limits

    @staticmethod
    def _parse_fmt(fmt):
        # parse fmt string if not parsed yet
        if isinstance(fmt, _PPTableParsedFmt):
            return fmt
        if fmt is None:
            fmt = ""
        assert isinstance(fmt, str), f"{type(fmt)}: {fmt}"
        return _PPTableParsedFmt(fmt)

    def _set_parsed_fmt(self, parsed_fmt, other=None):
        # Set new format.
        #
        # Arguments:
        # - parsed_fmt: _PPTableParsedFmt, parsed 'fmt' string
        # - other: optional other PPTableFormat object. Is used when some
        # information is not present in the 'fmt'.

        assert isinstance(parsed_fmt, _PPTableParsedFmt)

        self.repr_structure._set_parsed_fmt(
            parsed_fmt.cols_parsed_fmt, other.repr_structure)

        if parsed_fmt.vis_lines is None:
            # this section was not specified in fmt
            if other is None:
                self.set_limits(self._DFLT_LIMIT_LINES)
            else:
                self.limit_flines = other.limit_flines
                self.limit_llines = other.limit_llines
        else:
            self.set_limits(parsed_fmt.vis_lines)

    def __repr__(self):
        # it's important that repr contains fmt string, which can be used
        # to construct new format objects
        return self._get_fmt_str()

    def __str__(self):
        return self._get_fmt_str()

    def _get_fmt_str(self) -> str:
        # create the 'fmt' string which describes self.

        parts = []
        # 1. format of visible columns
        parts.append(str(self.repr_structure))

        # 2. numbers of visible lines
        if self.any_lines_skipped is None or self.any_lines_skipped is True:
            if self.limit_flines is None or self.limit_llines is None:
                parts.append("*")
            else:
                parts.append(f"{self.limit_flines}:{self.limit_llines}")
        else:
            # no lines skipped, no need to include these limits into fmt
            parts.append("")

        # 3. format max table width
        # not implemented

        while parts and parts[-1] == "":
            parts.pop()

        return ";".join(parts)


#########################
# PPEnumFieldType

class PPEnumFieldType(FieldType):
    """PPTable Enum Field Type.

    Generates values for PPTable cells, f.e.: "10 Active"
    """
    class EnumPalette(FieldType.PALETTE_CLASS):
        """Palette to be used for enum fields"""
        PARENT_PALETTES = [FieldType.PALETTE_CLASS, ]

        value = ConfColor('')
        name_good = ConfColor('')
        name_warn = ConfColor('')
        error = ConfColor('ERROR')

    PALETTE_CLASS = EnumPalette
    MISSING = object()

    _FMT_MODIFIERS = {
        'full': "show both value and name, (f.e. '10 Active')",
        'val': "show only value of the enum, (f.e. '10')",
        'name': "show only name of the enum value, (f.e. 'Active')",
    }

    def __init__(self, enum_values):
        """Create PPEnumFieldType.

        Arguments:
        - enum_values: {enum_val: enum_name} or {enum_val: (enum_name, syntax_name)}

        Use PPEnumFieldType.MISSING value to specify description and syntax
        of 'unexpected' values.
        """
        self.enum_values = {
            enum_val: (
                (enum_name, None) if not isinstance(enum_name, (list, tuple))
                else enum_name
            )
            for enum_val, enum_name in enum_values.items()
        }
        self.enum_missing_value = enum_values.get(
            self.MISSING, ("<???>", "error"))

        self.max_val_len = max(
            (len(str(x)) for x in self.enum_values if x is not None),
            default=1)

        # {syntax_names_id: {fmt_modifier: {enum_val: (text, align)}}}
        self._cache = {}

        self._cache_lengths = {
            fmt_modifier: {}
            for fmt_modifier in self._FMT_MODIFIERS
        }  # {fmt_modifier: {enum_val: length}}
        self._cache_lengths[None] = self._cache_lengths['full']
        super().__init__()

    def val_to_name(self, value) -> str:
        """Return simple string name of the value."""
        return self.enum_values.get(value, self.enum_missing_value)[0]

    def make_desired_cell_ch_chunks(
        self, value, fmt_modifier, field_palette,
    ) -> ([CHText.Chunk], int):
        """value -> desired text and alignment"""

        cache_key = id(field_palette)  # need to maintain separate caches
                            # enum_value -> CTHText for different palettes
        # prepare and cache cell text for a enum value
        # cache is prepared for all supported format modifiers
        try:
            by_fmt_cache = self._cache[cache_key]
        except KeyError:
            by_fmt_cache = self._cache[cache_key] = {
                fmt_modifier: {}
                for fmt_modifier in self._FMT_MODIFIERS
            }
            # None and 'full' format modifiers will refer to the same cached vals
            by_fmt_cache[None] = by_fmt_cache['full']
            self._cache[cache_key] = by_fmt_cache

        by_value_cache = by_fmt_cache.get(fmt_modifier, None)
        if by_value_cache is None:
            self._verify_fmt_modifier(fmt_modifier)

        if value not in by_value_cache:
            self._make_text_cache_for_val(
                value, field_palette, by_fmt_cache)

        return by_value_cache[value]

    def _make_text_cache_for_val(self, value, cp, by_fmt_cache) -> None:
        # populate self._cache for value
        # ('by_fmt_cache' is part of self._cache)
        try:
            name, syntax_name = self.enum_values[value]
            val_len = self.max_val_len
        except KeyError:
            if value is None:
                # special case: cell will not contain enum's value and name,
                # but a single None
                text_and_alignment = super().make_desired_cell_ch_chunks(
                    value, None, cp)
                by_fmt_cache['val'][value] = text_and_alignment
                by_fmt_cache['name'][value] = text_and_alignment
                by_fmt_cache['full'][value] = text_and_alignment
                return
            name, syntax_name = self.enum_missing_value
            val_len = max(self.max_val_len, len(str(value)))

        color_fmt = cp.get_color(syntax_name)

        # 'val' format
        val_text_items, align = super().make_desired_cell_ch_chunks(value, None, cp)
        by_fmt_cache['val'][value] = (val_text_items, align)

        # 'name' format
        by_fmt_cache['name'][value] = ([color_fmt(name)], align)

        # 'full' format
        full_text_items = []
        pad_len = val_len - CHText.calc_chunks_len(val_text_items)
        if pad_len > 0:
            # align 'value' portion of the text to right
            full_text_items.append(cp.text(" " * pad_len))
        full_text_items.extend(val_text_items)
        full_text_items.append(cp.text(" "))
        full_text_items.append(color_fmt(name))
        by_fmt_cache['full'][value] = (full_text_items, self.ALIGN_LEFT)

    def get_cell_text_len(self, value, fmt_modifier) -> int:
        """Calculate length of text representation of the value."""

        by_val_lenghs = self._cache_lengths.get(fmt_modifier, None)
        if by_val_lenghs is None:
            self._verify_fmt_modifier(fmt_modifier)

        if value not in by_val_lenghs:
            self._make_len_cache_for_val(value)

        return by_val_lenghs[value]

    def _make_len_cache_for_val(self, value):
        # populate self._cache_lengths for value
        try:
            name, _ = self.enum_values[value]
            val_len = self.max_val_len
        except KeyError:
            if value is None:
                # special case: cell will not contain enum's value and name,
                # but a single None
                text_len = len(str(None))
                self._cache_lengths['val'][value] = text_len
                self._cache_lengths['name'][value] = text_len
                self._cache_lengths['full'][value] = text_len
                return
            name, _ = self.enum_missing_value
            val_len = max(self.max_val_len, len(str(value)))

        # 'val' format
        self._cache_lengths['val'][value] = val_len

        # 'name' format
        name_len = len(str(name))
        self._cache_lengths['name'][value] = name_len

        # 'full' format
        self._cache_lengths['full'][value] = val_len + 1 + name_len

    def is_fmt_modifier_ok(self, fmt_modifier) -> (bool, str):
        """Chek if fmt_modifier is correct."""
        if fmt_modifier is None or fmt_modifier in self._FMT_MODIFIERS:
            return True, ""

        formats_descr = "\n".join(
            f"'{fmt_name}': {fmt_descr}"
            for fmt_name, fmt_descr in self._FMT_MODIFIERS.items())

        return False, (
            f"Format modifier '{fmt_modifier}' is not supported by "
            f"{str(type(self))}. Supported format modifiers: \n"
            f"{formats_descr}"
        )
