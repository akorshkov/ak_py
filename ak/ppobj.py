"""Methods for pretty-printing tables and json-like python objects.

Classes provided by this module:
- PrettyPrinter - pretty-printer of json-like python structures
- PPObj - base class for objects which have colored text representation
- PPTable - pretty-printable 2-D tables
- PPEnumFieldType - to be used by PPTable for enum fields
"""

from typing import Iterator
from numbers import Number
from ak import utils
from ak.color import CHText, Palette, CompoundPalette, PaletteUser, ConfColor

ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT = 1, 2, 3
CELL_TYPE_TITLE, CELL_TYPE_BODY = 11, 22


class CHTextResult:
    """CHTextResult can be used either as a usual CHText object, or as iterator.

    Single PPObj object can either produce a single CHText or generate multiple
    CHText objects (usually corresponding to single lines of the multi-line text).
    CHTextResult produced by PPObj may be used in both contexts.
    """
    __slots__ = 'ppobj', 'cp', '_ch_text'

    def __init__(self, ppobj, cp):
        self.ppobj = ppobj
        self.cp = cp
        self._ch_text = None

    def __str__(self):
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return self._ch_text.__str__()

    def plain_text(self) -> str:
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return self._ch_text.plain_text()

    @classmethod
    def strip_colors(cls, text: str) -> str:
        """Colorer-formatted string -> same string w/o coloring."""
        return CHText.strip_colors(text)

    def get_ch_text(self) -> CHText:
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return CHText(self._ch_text)

    def __len__(self):
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return len(self._ch_text)

    def __eq__(self, other):
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)

        return self._ch_text.__eq__(other)

    def __iadd__(self, other) -> CHText:
        return self + other

    def __add__(self, other) -> CHText:
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return self._ch_text + other

    def __radd__(self, other) -> CHText:
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return other + self._ch_text

    def __getitem__(self, index) -> CHText:
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return self._ch_text.__getitem__(index)

    def fixed_len(self, desired_len) -> CHText:
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return self._ch_text.fixed_len(desired_len)

    def __format__(self, format_spec):
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        return self._ch_text.__format__(format_spec)

    def __eq__(self, other):
        if self._ch_text is None:
            self._ch_text = self.ppobj.make_ch_text(self.cp)
        if isinstance(other, CHTextResult):
            other = other.get_ch_text()
        return self._ch_text.__eq__(other)

    def __iter__(self):
        return self.ppobj.gen_ch_lines(self.cp)


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
        no_color=False,
        colors_conf=None,
    ) -> CHTextResult:
        """obj_to_print -> pretty-printed colored text.

        Arguments:
        - obj_to_print: object to print
        - palette: optional PrettyPrinter.PPPalette-derived class or an object of
            such class, contains colors to be used
        - no_color: optional bool; True indicates that produced text will contain
            no colors
        - colors_conf: optional, global colors config. Is used for testing
            purposes only
        """
        palette = self._mk_palette(palette, no_color, colors_conf)
        ppobj = _PrettyPrinterTextGen(self, obj_to_print)
        return CHTextResult(ppobj, palette)

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

    In order to mae it possible to format colored text CHText is used.
    CHText object keeps track of printable and not-printable characters, so that
    it is possible to use it in f-strings with width format specifiers.

    PPObj.ch_fmt() method returns ak.color.CHTextResult object. This object is
    similar to CHText, but can be used as iterator of CHText objects (usualy
    corresponding to the lines of multi-line text)

    PPObj-derived class should implement at least one of the two methods:
    - make_ch_text(cp: Palette) -> CHText
    - gen_ch_lines(cp: Palette) -> Iterator[CHText]

    (See PaletteUser class documentation for more details).
    """

    def __str__(self):
        return str(self.ch_fmt())

    def ch_fmt(
        self, *, palette=None, no_color=False, colors_conf=None,
    ) -> CHTextResult:
        """Return CHTextResult - colored representation of self.

        Arguments:
        - palette: (optional) Either Palette-derived class or an object of such type
        - no_color: instructs to produce text without color effects,
            False by default
        - colors_conf: global colors config is used by default. Explicitely
            used for testing purposes only
        """
        return CHTextResult(
            self,
            self._mk_palette(palette, no_color, colors_conf))

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


#########################
# PPTable

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
            'TABLE.COL_TITLE': "GREEN:bold",
            'TABLE.NUMBER': "NUMBER",
            'TABLE.KEYWORD': "KEYWORD",
            'TABLE.WARN': "WARN",
        }

        SUB_PALETTES_MAP = {}

        border = ConfColor('TABLE.BORDER')
        col_title = ConfColor('TABLE.COL_TITLE')
        number = ConfColor('TABLE.NUMBER')
        keyword = ConfColor('TABLE.KEYWORD')
        warn = ConfColor('TABLE.WARN')

    PALETTE_CLASS = TablePalette

    def __init__(
            self, records, *,
            header=None,
            footer=None,
            fmt=None,
            fmt_obj=None,
            limits=None,
            skip_columns=None,
            fields=None,
            title_records=None,
            fields_types=None,
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
            of PPTableField objects
        - title_records: (optional) list of objects which have format similar to
            elements of 'records' argument, but contain information for
            multi-line titles
        - fields_types: (optional) dictionary {field_name: PPTableFieldType}.

        Combinations of arguments used in common scenarios:

        PPTable(
            records,
            fmt="field_a, field_b",  # names of fields for visible columns
            fields=["field_1", ...],  # correspondence of fields to values in record
            fields_types={...}, # PPTableFieldType for those fields, for which
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

        # self._default_pptable_printer produces 'default' representation of the table
        # (that is what is produced by 'print(pptable)')
        self._default_pptable_printer = _PPTableImpl(
            records,
            header=header,
            footer=footer,
            fmt=fmt,
            fmt_obj=fmt_obj,
            limits=limits,
            skip_columns=skip_columns,
            fields=fields,
            title_records=title_records,
            fields_types=fields_types,
        )

    def set_fmt(self, fmt):
        """Specify fmt - a string which describes format of the table.

        Method returns self - so that in python console the modified table be
        printed out immediately.
        """
        self._default_pptable_printer.set_fmt(fmt)
        return self

    def _get_fmt(self):
        # getter of 'fmt' property.
        # returns PPTableFormat object
        # repr of this object contains fmt string which can be used to apply
        # new format
        return self._default_pptable_printer._get_fmt()

    fmt = property(_get_fmt, set_fmt)

    def remove_columns(self, columns_names):
        """Remove columns from table.

        Arguments:
        - columns_names: list of names of columns to remove. (values not
            equal to name of any column are accepted but ignored).
        """
        self._default_pptable_printer.remove_columns(columns_names)

    def gen_ch_lines(self, cp: Palette) -> Iterator[CHText]:
        # implementation of PrettyPrinter functionality
        yield from self._default_pptable_printer.gen_ch_lines(cp)


class PPTableFieldType(PaletteUser):
    """Describe specific field in table records.

    Actual column of of PPTable corresponds to a records field, (f.e. some
    column displays 'name' of records), the way information is displayed
    depends on PPTableFieldType associated with this field.
    """

    # default field uses same palette as table
    PALETTE_CLASS = PPTable.TablePalette

    def __init__(self, min_width=1, max_width=999):
        self.min_width = min_width
        self.max_width = max_width

    def get_cell_text_len_for_row_type(self, value, fmt_modifier, cell_type) -> int:
        if cell_type == CELL_TYPE_TITLE:
            return self.get_title_cell_text_len(value, fmt_modifier)
        return self.get_cell_text_len(value, fmt_modifier)

    def get_cell_text_len(self, value, fmt_modifier) -> int:
        """Calculate length of text representation of the value (for usual cell)

        This implementation is universal, but inefficient. Override in
        derived classes to avoid construction of syntax items objects - usually
        it is not required to find out text length.
        """
        ch_text_chunks, _ = self.make_desired_cell_ch_text(
            value, fmt_modifier,
            self.PALETTE_CLASS(no_color=True))
        return CHText.calc_chunks_len(ch_text_chunks)

    def get_title_cell_text_len(self, value, fmt_modifier) -> int:
        """Calculate len of the title of a table column."""
        # Default implementation does not use fmt_modifier argument
        # pylint: disable=unused-argument
        return len(str(value))

    def make_desired_cell_ch_text(
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
            align = ALIGN_RIGHT
        elif isinstance(value, Number):
            color_fmt = cp.number
            align = ALIGN_RIGHT
        else:
            color_fmt = cp.text
            align = ALIGN_LEFT
        return [color_fmt(str(value))], align

    def make_desired_title_cell_text(
        self, value, _fmt_modifier, cp,
    ) -> ([CHText.Chunk], int):
        """value -> desired text and alignment for title table row."""

        # values for column title cells are fetched from so called title records
        # which have same structure as usual records.
        # but these values supposed to be just strings, that is some description of
        # column. It is not a enum or uuid - it makes no need to format these values
        # using fmt_modifier.
        return [cp.col_title(str(value) if value else "")], ALIGN_CENTER

    def make_title_cell_ch_text(self, value, width, table_palette) -> [CHText.Chunk]:
        """Prepare list of CHText.Chunk for table title cell."""
        title_ch_chunks = [table_palette.col_title(str(value))]
        return self.fit_to_width(
            title_ch_chunks, width, ALIGN_LEFT, table_palette)

    def make_cell_ch_text(
        self, value, fmt_modifier, width,
        field_palette, table_palette,
    ) -> [CHText.Chunk]:
        """value -> [CHText.Chunk] having exactly specified width."""
        text, align = self.make_desired_cell_ch_text(
            value, fmt_modifier, field_palette)

        return self.fit_to_width(text, width, align, table_palette)

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

    @staticmethod
    def fit_to_width(ch_chunks, width, align, cp) -> [CHText.Chunk]:
        """[CHText.Chunk] -> [CHText.Chunk] of exactly specified length.

        Arguments:
        - ch_chunks: list of CHText.Chunk objects
        - width: desired width of result
        - align: pbobj.ALIGN_LEFT or pbobj.ALIGN_CENTER or pbobj.ALIGN_RIGHT
        - warn_syntax_name: in case the text does not fit into width
            it is not simply truncated, but modified - warn_syntax_name is required
            to get a color to be used to indicate modifications

        Examples:
        'short'            -> colored 'short    '  or '    short'
        'very long text'   -> colored 'very l...'
        """
        assert width >= 0
        filler_len = width - CHText.calc_chunks_len(ch_chunks)
        if filler_len == 0:
            return ch_chunks  # lucky, the text has exactly necessary length
        if filler_len > 0:
            if align == ALIGN_CENTER:
                left_filer_len = filler_len // 2
                right_filler_len = filler_len - left_filer_len
                result = [cp.text(' '*left_filer_len)]
                result.extend(ch_chunks)
                result.append(cp.text(' '*right_filler_len))
                return result
            filler = cp.text(' '*filler_len)
            if align == ALIGN_LEFT:
                return ch_chunks + [filler, ]
            assert align == ALIGN_RIGHT
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


class _PPTDefaultFieldType(PPTableFieldType):
    # implements more efficient implementation of get_cell_text_len

    def get_cell_text_len(self, value, _fmt_modifier):
        """Calculate length of text representation of the value."""
        # caluculate text length w/o constructing SHText object for the cell
        return len(str(value))


class _PPTableParsedFmt:
    # parser of fmt - string representing PPTable format

    __slots__ = ('fmt', 'columns', 'vis_lines', 'table_width')

    class _ParsedColFmt(utils.DataRecord):
        # parsed information about a single column
        __slots__ = ['fmt', 'field_name', 'fmt_modifier', 'break_by',
                     'value_path', 'min_w', 'max_w', 'cur_w']

    def __init__(self, fmt):
        """Parse fmt - string containing PPTable format description"""
        self.fmt = fmt

        if fmt is None:
            fmt = ";;"

        # 0. fmt is "visible_columns ; visible_records ; table_width"
        fmt_s_cols, fmt_s_lines, _fmt_s_twidths = self._fmt_str_split(fmt)

        self.columns = self._parse_cols_fmt(fmt_s_cols)
        self.vis_lines = self._parse_vis_lines_fmt(fmt_s_lines)
        self.table_width = None  # not implememnted

    def contains_fields_info(self):
        """Check if any column info contains field-specific information.

        Field-specific information is path to value in record object
        (smthn like '<-0.department.[main]' in fmt string)
        """
        if self.columns in ["", "*"]:
            return False

        return any(col.value_path is not None for col in self.columns)

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

        fieldnames_wo_value_path = {
            fn for fn in fieldnames_wo_value_path
            if fn not in path_by_field_name
        }

        if fieldnames_wo_value_path:
            raise ValueError(
                f"value_paths not found in columns descriptions for the following "
                f"fields: {fieldnames_wo_value_path}. Original fmt:\n'{self.fmt}'")

        return path_by_field_name

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
        """Check if fmt contains explicit columns list (not special value)."""
        return self.columns not in ["", "*"]

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

    def _parse_cols_fmt(self, fmt_s_cols):
        # constructor helper: parse 'columns' part of the fmt string
        if fmt_s_cols in ("", "*"):
            return fmt_s_cols  # special values "change nothing" and "show all"

        return [self._parse_col_fmt(s) for s in fmt_s_cols.split(',')]

    @classmethod
    def _parse_col_fmt(cls, fmt):
        # constructor helper: parse a single column fmt descr -> _ParsedColFmt
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

        # 1.2. ignore the optional current actual width
        i = width_fmt.find('(')
        if i >= 0:
            cur_w_str = width_fmt[i:]
            if not cur_w_str.endswith(')'):
                raise ValueError(
                    f"invalid column fmt '{fmt}'; no closing paren "
                    f"found in curent width description '{cur_w_str}'")
            cur_w_str = cur_w_str[1:-1]
            try:
                result.cur_w = int(cur_w_str)
            except ValueError as err:
                raise ValueError(
                    f"invalid column fmt '{fmt}'; invalid current "
                    f"width description '{cur_w_str}'") from err
            width_fmt = width_fmt[:i]

        # 1.3. parse width limits
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


class PPTableField:
    """Describes source of data for a column of PPTable.

    Each column of a table refers to some field. The field contains rules how
    to fetch a value for this column from a record and information about type
    of this value (for example possible alternative ways to represent the value)

    Table can have several (or none) actual columns corresponding to the same field.
    """

    def __init__(self, name, value_path, field_type,
                 min_width=None, max_width=None):
        """PPTableField constructor."""
        self.name = name
        self.field_type = field_type
        self.value_path = self._prepare_value_path(value_path, name)
        self.min_width = min_width if min_width is not None else field_type.min_width
        self.max_width = max_width if max_width is not None else field_type.max_width

    def fetch_value(self, record):
        """get value from a record according to the rules specified by value_path."""
        val = record
        for is_attr, key in self.value_path:
            if is_attr:
                val = getattr(val, key)
            else:
                val = val[key]
        return val

    @classmethod
    def _prepare_value_path(cls, value_path, field_name):
        # "0.name" -> [(False, 0), (True, 'name')]
        # "1.[name]" -> [(False, 0), (False, 'name')]
        # "0." -> [(False, 0), (True, 'field_name')]
        if isinstance(value_path, int):
            return [(False, value_path)]
        assert isinstance(value_path, str)

        prepared_path = []

        steps = [s.strip() for s in value_path.split('.')]
        for step in steps:
            in_brakets = False
            if step.startswith('[') and step.endswith(']'):
                in_brakets = True
                step = step[1:-1]

            key = cls._opt_convert_int(step)
            is_attr = isinstance(key, str) and not in_brakets
            prepared_path.append((is_attr, key))

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


class PPTableColumn:
    """Column of a PPTable.

    Part of PPTableFormat, describes properties of actual column of the table.
    """

    def __init__(self, field, name, fmt_modifier, break_by,
                 min_width, max_width):
        """PPTableColumn constructor.

        Arguments:
        - field: PPTableField, specifies position of corresponding velue in
            record and formatting rules
        - name: name of column
        - fmt_modifier: in case PPTableField supports several ways to format
            the value (f.e. long and short form of uuid) - specifies how to
            format the value.
        - break_by: indicates that an empty row should be inserted into table
            whenever the value of this column changes.
        - min_width, max_width: limits for column width.
        """
        self.field = field  # PPTableField
        self.name = name

        self.field.field_type._verify_fmt_modifier(fmt_modifier)
        self.fmt_modifier = fmt_modifier
        self.break_by = break_by

        self.min_width = min_width if min_width is not None else field.min_width
        self.max_width = max_width if max_width is not None else field.max_width
        self.width = None  # actual width of the column, will be calculated later

    def clone(self):
        """Clone self. (except for 'width' attribute)"""
        return PPTableColumn(
            self.field,
            self.name,
            self.fmt_modifier,
            self.break_by,
            self.min_width,
            self.max_width,
        )

    def get_cell_text_len(self, record, cell_type):
        """Get desired cell length for this value.

        (Actual cell may be shorter or longer).
        """
        value = self.field.fetch_value(record)
        return self.field.field_type.get_cell_text_len_for_row_type(
            value, self.fmt_modifier, cell_type)

    def make_cell_ch_text(
        self, record, cell_type, field_palette, table_palette,
    ) -> [CHText.Chunk]:
        """Fetch value from record and make colored text for a cell.

        Length of created text is exactly self.width.
        """
        value = self.field.fetch_value(record)
        if cell_type == CELL_TYPE_TITLE:
            return self.make_title_cell_ch_text_by_value(value, table_palette)

        return self.field.field_type.make_cell_ch_text(
            value, self.fmt_modifier, self.width,
            field_palette, table_palette,
        )

    def make_title_cell_ch_text_by_value(
        self, value, table_palette,
    ) -> [CHText.Chunk]:
        """Prepare list of CHText.Chunk for table title cell."""
        return self.field.field_type.make_title_cell_ch_text(
            value, self.width, table_palette)

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

    _DFLT_FIELD_TYPE = _PPTDefaultFieldType()
    _DFLT_LIMIT_LINES = (30, 20)  # n_first, n_last

    def __init__(
            self, fields, columns, limit_flines=None, limit_llines=None):
        """Constructor of PPTableFormat.

        Arguments:
        - fields: [PPTableField, ] - possible 'sources' of columns
        - columns: [PPTableColumn, ] - format of visible columns
        - limit_flines, limit_llines - limits of numbers of visible lines

        In most cases you would better use alternative constructors:
        - mk_by_other
        - mk_by_fields_names
        - mk_by_fields
        - mk_by_extended_fmt
        - mk_by_fmt
        - mk_auto_columns_names
        - mk_dummy_empty
        """
        self.fields = fields
        self.columns = [c.clone() for c in columns]  # [PPTableColumn, ]
        self.limit_flines = limit_flines
        self.limit_llines = limit_llines
        # indicates if the table (which ownes this format object) has more lines
        # than can be displayed (because of self.limit_flines and self.limit_llines
        # limits)
        self.any_lines_skipped = None

    @classmethod
    def mk_by_other(cls, fmt, other):
        """Copy-constructor of PPTableFormat."""
        fmt_obj = cls(
            other.fields, other.columns, other.limit_flines, other.limit_llines)
        if fmt is not None:
            parsed_fmt = cls._parse_fmt(fmt)
            parsed_fmt.verify_not_enhanced()
            fmt_obj._set_parsed_fmt(parsed_fmt, other)
        return fmt_obj

    @classmethod
    def mk_by_fields_names(cls, fmt, fields_names, fields_types):
        """Constructor of PPTableFormat.

        To be used if records for the table are simple tuples/lists of values.

        Arguments:
        - fmt: format string (or _PPTableParsedFmt). Check PPTableFormat doc.
        - fields_names: list of names of values (must correspond to values
            in actual records)
        - fields_types: {field_name: PPTableFieldType} - can be used to
            specify not-default types of fields.
        """
        fields = [
            PPTableField(
                name, pos,
                fields_types.get(name, cls._DFLT_FIELD_TYPE),
            ) for pos, name in enumerate(fields_names)]

        return cls.mk_by_fields(fmt, fields)

    @classmethod
    def mk_by_fields(cls, fmt, fields):
        """Constructor of PPTableFormat.

        To be used if records for the table are simple tuples/lists of values.

        Arguments:
        - fmt: format string (or _PPTableParsedFmt). Check PPTableFormat doc.
        - fields: [PPTableField, ]
        """
        fmt_obj = cls(fields, [])
        parsed_fmt = cls._parse_fmt(fmt)
        parsed_fmt.verify_not_enhanced()
        fmt_obj._set_parsed_fmt(parsed_fmt)
        return fmt_obj

    @classmethod
    def mk_by_extended_fmt(cls, fmt, fields_types):
        """Constructor of PPTableFormat.

        To be used if records for the table have complex structure, so that it's
        necessary to specify a 'path' to a value. For example value for a field
        'name' is record[1].contact['main'].name.

        Arguments:
        - fmt: "extended" format string (or parsed one) - columns descriptions
            must contain paths to values. Check PPTableFormat doc.
        - sample: the sample record. Expected an object with _fields -
            list of names of values. Usually an object of namedtuple-derived class.
        - fields_types: {field_name: PPTableFieldType} - can be used to
            specify not-default types of fields.
        """
        parsed_fmt = cls._parse_fmt(fmt)
        value_path_by_field = parsed_fmt.get_fields_info()

        fields = [
            PPTableField(
                c.field_name, value_path_by_field[c.field_name],
                fields_types.get(c.field_name, cls._DFLT_FIELD_TYPE),
            ) for c in parsed_fmt.columns]

        fmt_obj = cls(fields, [])
        fmt_obj._set_parsed_fmt(parsed_fmt)
        return fmt_obj

    @classmethod
    def mk_by_fmt(cls, fmt, sample_record, fields_types):
        """Constructor of PPTableFormat.

        To be used if records are simple lists/tuples and there is no other
        information about fields except for columns described in fmt. In this
        case fields will be created based on columns descriptions.

        Arguments:
        - fmt: format string (or _PPTableParsedFmt). Check PPTableFormat doc.
        - sample_record: if provided it will be used to check if guessed fields
            information matches the samle
        - fields_types: {field_name: PPTableFieldType} - can be used to
            specify not-default types of fields.
        """
        parsed_fmt = cls._parse_fmt(fmt)
        assert isinstance(parsed_fmt.columns, (list, tuple))
        if sample_record is not None:
            if not isinstance(sample_record, (list, tuple)):
                raise ValueError(
                    f"This PPTableFormat constructor may be used only if table "
                    f"records are 'simple' (lists or tuples). The sample record "
                    f"is not 'simple': {type(sample_record)} {sample_record}. ")
            if len(parsed_fmt.columns) != len(sample_record):
                raise ValueError(
                    f"This PPTableFormat constructor expects that all the record "
                    f"fields correspond to columns specified in format. Number of "
                    f"fields in sample record is {len(sample_record)}: "
                    f"{sample_record}.\n"
                    f"Number of columns in format is {len(parsed_fmt.columns)}:\n"
                    f"{parsed_fmt.fmt}")
        fields_names = [c.field_name for c in parsed_fmt.columns]
        return cls.mk_by_fields_names(parsed_fmt, fields_names, fields_types)

    @classmethod
    def mk_auto_columns_names(cls, fmt, sample_record):
        """Constructor of PPTableFormat.

        To be used if records are simple lists/tuples and there is no other
        information fields names. We can only guess number of fields by
        sample_record. Fields names will be auto-generated.

        Arguments:
        - fmt: format string (or _PPTableParsedFmt). Check PPTableFormat doc.
        - sample_record: sample record
        """
        assert sample_record is not None
        if not isinstance(sample_record, (list, tuple)):
            raise ValueError(
                f"This PPTableFormat constructor may be used only if table "
                f"records are 'simple' (lists or tuples). The sample record "
                f"is not 'simple': {type(sample_record)} {sample_record}. ")
        fields_names = [
            f"col_{i}" for i in range(1, 1+len(sample_record))]
        return cls.mk_by_fields_names(fmt, fields_names, {})

    @classmethod
    def mk_dummy_empty(cls, fmt):
        """Constructor of PPTableFormat.

        It is not possible to get any information about fields/columns. But
        the table is empty anyway. Create a table with a single quasi-column.

        Arguments:
        - fmt: format string (or _PPTableParsedFmt). This constructor is called
            only if fmt contains no useful information, it will be used as dummy.
        """
        fields_names = ['-                              -', ]
        return cls.mk_by_fields_names(fmt, fields_names, {})

    def remove_columns(self, columns_names):
        """Remove columns from table."""
        self.columns = [
            c for c in self.columns
            if c.name not in columns_names
        ]

    def set_limits(self, limits):
        """Change number of printrable records.

        Possible values:
        - (n_first, n_last): tuple of two optional integers
        """
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

        fields_by_name = {f.name: f for f in self.fields}

        # 1. create list of columns
        columns = []
        if parsed_fmt.columns == "" and other is not None:
            # copy columns from the other
            columns = [c.clone() for c in other.columns]
        elif parsed_fmt.columns in ("", "*"):
            # show column for each field
            for field in self.fields:
                columns.append(PPTableColumn(
                    field, field.name,
                    None,  # fmt_modifier
                    False,  # break_ty
                    field.min_width, field.max_width))
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

                columns.append(PPTableColumn(
                    field, c.field_name,
                    c.fmt_modifier, c.break_by,
                    c.min_w, c.max_w))

        self.columns = columns

        # 2. process visible lines limits
        if parsed_fmt.vis_lines is None:
            # this section was not specified in fmt
            if other is None:
                self.limit_flines, self.limit_llines = self._DFLT_LIMIT_LINES
            else:
                self.limit_flines = other.limit_flines
                self.limit_llines = other.limit_llines
        else:
            self.limit_flines, self.limit_llines = parsed_fmt.vis_lines

    def __repr__(self):
        # it's important that repr contains fmt string, which can be used
        # to construct new format objects
        return self._get_fmt_str()

    def __str__(self):
        return self._get_fmt_str()

    def _get_fmt_str(self):
        # create the 'fmt' string which describes self.

        parts = []
        # 1. format of visible columns
        parts.append(",".join(c.to_fmt_str() for c in self.columns))

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


class _PPTableImpl:
    # Implements pretty-printing of table

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
            title_records=None,
            fields_types=None,
    ):
        # check doc of PPTable for description of aruments

        self.records = records

        self._ppt_fmt = self._init_format(fmt, fmt_obj, fields, fields_types)
        if limits is not None:
            self._ppt_fmt.set_limits(limits)
        if skip_columns is not None:
            self._ppt_fmt.remove_columns(skip_columns)

        self.title_records = title_records or []

        self.header = header
        self.footer = (
            footer if footer is not None else f"Total {len(self.records)} records")

    def _init_format(self, fmt, fmt_obj, fields, fields_types) -> PPTableFormat:
        # part of PPTable constructor.
        # depending on arguments choose apropriate way to create PPTableFormat
        fields_types_dict = {} if fields_types is None else fields_types

        if fmt_obj is not None:
            assert fields is None
            assert fields_types is None
            assert fmt is None
            return PPTableFormat.mk_by_other(None, fmt_obj)

        parsed_fmt = PPTableFormat._parse_fmt(fmt)

        if fields is not None:
            assert fmt_obj is None
            assert not parsed_fmt.contains_fields_info()
            if all(isinstance(fn, str) for fn in fields):
                return PPTableFormat.mk_by_fields_names(
                    parsed_fmt, fields, fields_types_dict)
            else:
                assert all(isinstance(f, PPTableField) for f in fields)
                assert fields_types is None
                return PPTableFormat.mk_by_fields(parsed_fmt, fields)

        if parsed_fmt.contains_fields_info():
            assert fields is None
            return PPTableFormat.mk_by_extended_fmt(parsed_fmt, fields_types_dict)

        sample_record = self.records[0] if self.records else None

        if hasattr(sample_record, '_fields'):
            # very good, sample record contains explicit names of fields
            # (probably it is a namedtuple)
            return PPTableFormat.mk_by_fields_names(
                parsed_fmt, sample_record._fields, fields_types_dict)

        if parsed_fmt.cols_are_explicit():
            # no info about fields names. But we know what columns the table
            # is expected to have. If columns correspond to record (or there
            # is no records at all) - let's create fields based on columns
            return PPTableFormat.mk_by_fmt(
                parsed_fmt, sample_record, fields_types_dict)

        # columns are not specified
        if sample_record:
            return PPTableFormat.mk_auto_columns_names(
                parsed_fmt, sample_record)

        # table is empty and there is no information about it's columns.
        return PPTableFormat.mk_dummy_empty(parsed_fmt)

    def set_fmt(self, fmt):
        """Specify fmt - a string which describes format of the table."""
        self._ppt_fmt = PPTableFormat.mk_by_other(fmt, other=self._ppt_fmt)
        return self

    def _get_fmt(self):
        # getter of 'fmt' property.
        return self._ppt_fmt

    def remove_columns(self, columns_names):
        """Remove columns from table."""
        self._ppt_fmt.remove_columns(columns_names)

    def gen_ch_lines(self, cp: PPTable.TablePalette) -> Iterator[CHText]:
        """Generate CHText objects - lines of the printed table"""

        columns = self._ppt_fmt.columns
        record_fields_palettes = [
            cp.get_sub_palette(col.field.field_type.PALETTE_CLASS)
            for col in columns]
        title_fields_palettes = [cp for col in columns]

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
        for col in columns:
            col.width = min(col.max_width, max(col.min_width, len(col.name)))

        for cell_type, recs_generator in [
            (CELL_TYPE_TITLE, self.title_records),
            (CELL_TYPE_BODY, (
                rec for rec in table_lines
                if not isinstance(rec, self._ServiceLine)
            )),
        ]:
            for rec in recs_generator:
                for col in columns:
                    if col.width < col.max_width:
                        col.width = max(
                            col.width,
                            min(col.max_width, col.get_cell_text_len(rec, cell_type))
                        )
                if all(col.width == col.max_width for col in columns):
                    break

        table_width = sum(col.width for col in columns) + len(columns) + 1

        sep = cp.border('|')

        # contents of service lines can be created now
        break_line.ch_text = CHText(sep, " "*(table_width - 2), sep)
        skipped_line_contents = PPTableFieldType.fit_to_width(
            [
                cp.warn("... "),
                cp.text(f"{n_skipped} records skipped"),
            ],
            table_width - 2,
            ALIGN_LEFT,
            cp)
        skipped_line_contents.insert(0, sep)
        skipped_line_contents.append(sep)
        skipped_recs_line.ch_text = CHText.make(skipped_line_contents)

        # 1. make first border line
        border_line = CHText.make([
            cp.border("".join("+" + "-"*col.width for col in columns) + '+')])
        yield border_line

        # 2. table header (name)
        if self.header:
            line = PPTableFieldType.fit_to_width(
                [cp.col_title(self.header)], table_width - 2, ALIGN_LEFT, cp)
            line.insert(0, sep)
            line.append(sep)
            yield CHText.make(line)

        # 3. column names
        #
        # 'Names' part of the table consists of two sections:
        # - names of the columns
        # - (optional) title records
        # If a table has title records it looks as if the table has multi-line
        # column names. But the sources of data for these lines are different.
        # For the first line the source is the columns names, and for subsequent
        # lines it is explicitely specified record objects. Different processing
        # is required in these cases.
        #
        # 3.1. the first line of column names
        line = [sep]
        is_first = True
        for col in columns:
            if is_first:
                is_first = False
            else:
                line.append(sep)
            line.extend(
                col.make_title_cell_ch_text_by_value(col.name, cp))

        line.append(sep)
        yield CHText.make(line)

        # 3.2. multi-line column titles
        cols_and_palettes = list(zip(columns, title_fields_palettes))
        for title_rec in self.title_records:
            yield CHText.make(self._make_table_line(
                title_rec, cols_and_palettes, sep, CELL_TYPE_TITLE, cp))

        # 4. one more border_line
        yield border_line

        # 5. table contents - actual records and service lines
        cols_and_palettes = list(zip(columns, record_fields_palettes))
        for tl in table_lines:
            if isinstance(tl, self._ServiceLine):
                yield tl.ch_text
            else:
                yield CHText.make(self._make_table_line(
                    tl, cols_and_palettes, sep, CELL_TYPE_BODY, cp))

        # 6. final border line
        yield border_line

        # 7. summary line
        if self.footer:
            yield CHText.make(PPTableFieldType.fit_to_width(
                [cp.text(self.footer)], table_width, ALIGN_LEFT, cp))

    def _make_table_line(
        self, record, cols_and_palettes, sep, cell_type, cp,
    ) -> [CHText.Chunk]:
        # create CHText chunks - representaion of a single record in table
        line = [sep]
        is_first = True
        for col, field_palette in cols_and_palettes:
            if is_first:
                is_first = False
            else:
                line.append(sep)
            line.extend(col.make_cell_ch_text(record, cell_type, field_palette, cp))
        line.append(sep)
        return line


#########################
# PPEnumFieldType

class PPEnumFieldType(PPTableFieldType):
    """PPTable Enum Field Type.

    Generates values for PPTable cells, f.e.: "10 Active"
    """
    class EnumPalette(PPTableFieldType.PALETTE_CLASS):
        """Palette to be used for enum fields"""
        PARENT_PALETTES = [PPTableFieldType.PALETTE_CLASS, ]

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

    def make_desired_cell_ch_text(
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
                text_and_alignment = super().make_desired_cell_ch_text(
                    value, None, cp)
                by_fmt_cache['val'][value] = text_and_alignment
                by_fmt_cache['name'][value] = text_and_alignment
                by_fmt_cache['full'][value] = text_and_alignment
                return
            name, syntax_name = self.enum_missing_value
            val_len = max(self.max_val_len, len(str(value)))

        color_fmt = cp.get_color(syntax_name)

        # 'val' format
        val_text_items, align = super().make_desired_cell_ch_text(value, None, cp)
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
        by_fmt_cache['full'][value] = (full_text_items, ALIGN_LEFT)

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
