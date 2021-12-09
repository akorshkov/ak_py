"""Methods for pretty-printing tables and json-like python objects.

Classes provided by this module:
- PPJson - pretty-printable json-like structures
- PPTable - pretty-printable 2-D tables
"""

from typing import Iterator
from ak.color import ColorFmt, ColoredText

#########################
# generic pretty-printing


class _PrettyPrinterBase:
    # Interface of PrettyPrinter object

    def gen_pplines(self, obj_to_print) -> Iterator[str]:
        """Generate lines of pretty text. To be implemented in derived classes."""
        _ = obj_to_print
        raise NotImplementedError

    def get_pptext(self, obj_to_print) -> str:
        """obj_to_print -> pretty string."""
        return "\n".join(self.gen_pplines(obj_to_print))


class PrettyPrinter(_PrettyPrinterBase):
    """Print json-like objects with color highliting."""

    # dafault colors
    _COLOR_NAME = ColorFmt('GREEN', bold=True)
    _COLOR_NUMBER = ColorFmt('YELLOW')
    _COLOR_KEYWORD = ColorFmt('BLUE', bold=True)

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

        Note: You can specify 'color_*' arguments to override predefined
            colors. Check help(ColorFmt.make) for possible values of these
            arguments.
        """
        self._color_name = ColorFmt.make(color_name, use_colors)
        self._color_number = ColorFmt.make(color_number, use_colors)
        self._color_keyword = ColorFmt.make(color_keyword, use_colors)

    def gen_pplines(self, obj_to_print) -> Iterator[str]:
        """Generate lines of colored text - pretty representation of the object."""

        line_chunks = []

        for chunk in self._gen_pp_str_for_obj(obj_to_print, offset=0):
            if chunk == "\n":
                yield "".join(line_chunks)
                line_chunks = []
            else:
                line_chunks.append(chunk)

        if line_chunks:
            yield "".join(line_chunks)

    def _gen_pp_str_for_obj(self, obj_to_print, offset=0) -> Iterator[str]:
        # generate parts for colored text result
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
            prefix = " " * (offset + 2)
            is_first = True
            for key in sorted_keys:
                if is_first:
                    is_first = False
                else:
                    yield ","
                yield "\n"
                yield prefix
                yield str(self._colorp_dict_key(key))
                yield ": "
                yield from self._gen_pp_str_for_obj(obj_to_print[key], offset+2)
            yield "\n"
            yield " " * offset + "}"
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
                prefix = " " * (offset + 2)
                yield "["
                is_first = True
                for item in obj_to_print:
                    if is_first:
                        is_first = False
                    else:
                        yield ","
                    yield "\n"
                    yield prefix
                    yield from self._gen_pp_str_for_obj(item, offset+2)
                yield "\n"
                yield " " * offset + "]"
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


class PPObj:
    """Base class for pretty-printable objects.

    PPobj is an object, whose __repr__ method prints (colored) representation
    of some data. The data itself is available in .r attribute of the object.

    Misc methods which are supposed to be used in python console return not
    a raw data, but PPobj.
    """

    def gen_pplines(self) -> Iterator[str]:
        """Generate lines of PPObj representation."""
        yield ""
        raise NotImplementedError

    def get_pptext(self):
        """Return string - PPObj representation."""
        return "\n".join(self.gen_pplines())

    def __repr__(self):
        # this method does not return text but prints it because the
        # text is supposed to be colored, and python console does not
        # print colored text correctly
        for line in self.gen_pplines():
            print(line)
        return ""

    def __str__(self):
        # do not remove it! Without this method the str(obj) will call
        # __repr__ which prints text immediately
        return self.get_pptext()


#########################
# pretty-printing json-like objects

class PPJson(PPObj):
    """Pretty-printable object for python json-like structures.

    repr of this object prints colored json.
    """

    _PPRINTER = PrettyPrinter()

    def __init__(self, obj_to_print):
        self.r = obj_to_print

    def gen_pplines(self) -> Iterator[str]:
        """Generate lines of colored text - repr of the self.r object."""
        yield from self._PPRINTER.gen_pplines(self.r)


#########################
# PPTable

class PPTable(PPObj):
    """2-D table.

    Provides pretty-printing and simple manipulation operations to 2-D table
    of data (such as results of sql query).
    """
    class _Column:
        def __init__(self, name, min_width, max_width):
            self.name = name
            self.min_width = min_width
            self.max_width = max_width

        def __str__(self):
            return f"<col {self.name} {self.min_width}-{self.max_width}>"

        def __repr__(self):
            return self.__str__()

    _DFLT_MIN_W = 3
    _DFLT_MAX_W = 50

    def __init__(self, name, field_names, records, columns=None):
        """PPTable constructor.

        Arguments:
        - name: name of the table
        - field_names: names of fields of records. Should correspond to records.
        - records: list of records (record is a tuple of values, corresponding
          to a row of the table)
        - columns: optional list of visible columns and their properties

        """
        self.name = name
        self.r = records  # pretty-printable object stores raw data in .r
        self.field_names = field_names

        self._field_pos_by_name = {}  # {field_name: [record_pos, ]}.
        for i, n in enumerate(self.field_names):
            self._field_pos_by_name.setdefault(n, []).append(i)

        self._columns = []
        self._cols_map = []

        self.set_columns(columns)

    def set_columns(self, columns=None):
        """Set visible columns.

        Arguments:
        - columns: optional list of visible columns. Each item is either:
            - field_id (either name or integer position in record)
            - (field_id, width)
            - (field_id, min_width, max_width)
        """
        n_fields = len(self.field_names)
        if columns is None:
            # make all columns visible
            self._columns = [
                self._Column(n, self._DFLT_MIN_W, self._DFLT_MAX_W)
                for n in self.field_names]
            self._cols_map = list(range(n_fields))
            return

        for col_attrs in columns:
            if not isinstance(col_attrs, (list, tuple)):
                col_attrs = [col_attrs, ]
            assert len(col_attrs) <= 3 and len(col_attrs) > 0
            field_id = col_attrs[0]
            if len(col_attrs) == 1:
                max_width, min_width = self._DFLT_MAX_W, self._DFLT_MIN_W
            elif len(col_attrs) == 2:
                max_width = col_attrs[1]
                min_width = self._DFLT_MIN_W
            else:
                max_width = col_attrs[1]
                min_width = col_attrs[2]

            if isinstance(field_id, int):
                col_pos = field_id
                assert col_pos >= 0 and field_id < len(n_fields), (
                    f"table column {col_attrs} refers field position {col_pos} "
                    f"- it must be in range [0, {n_fields}]. List of of record "
                    f"fields : {self.field_names}")
                field_name = self.field_names[col_pos]
            else:
                field_name = field_id
                assert field_id in self._field_pos_by_name, (
                    f"unknown field name {field_name}. Names of fields "
                    f"of records: {self.field_names}")
                field_poss = self._field_pos_by_name[field_name]
                assert len(field_poss) == 1, (
                    f"field name '{field_name}' can't be used in column definition "
                    f"because it's not unique. It refers to fields in positions "
                    f"{field_poss}. List of record fields: {self.field_names}")

                field_id = self._field_pos_by_name[field_name]

            col = self._Column(field_name, min_width, max_width)
            if col.max_width > 0:
                self._columns.append(col)
                self._cols_map.append(field_id)

    def gen_pplines(self) -> Iterator[str]:
        """Generate colored lines - text representation of the table."""
        table_printer  = _TablePrinter(
            self.name, self._columns, self._cols_map,
            self.r, max_rows=20)
        yield from table_printer.gen_screen_lines()


class _TablePrinter:
    # Generate text representation of DataTable

    _COLOR_BORDER = ColorFmt('GREEN')
    _COLOR_NAME = ColorFmt('GREEN', bold=True)
    _COLOR_NUMBER = ColorFmt('YELLOW')
    _COLOR_KEYWORD = ColorFmt('BLUE', bold=True)
    _COLOR_WARN = ColorFmt('RED')

    def __init__(self, name, columns, columns_map, records, max_rows=-1):
        self.name = name
        self.columns = columns
        self.columns_map = columns_map
        self.records = records

        if max_rows == -1 or max_rows > len(self.records):
            self.num_first_visible_rows = len(self.records)
            self.indicate_skipped_rows = False  #  "..." in place of skipped records
            self.num_last_visible_rows = 0
        elif max_rows >= 3:
            self.num_first_visible_rows = max_rows - 2
            self.indicate_skipped_rows = True
            self.num_last_visible_rows = 1
        elif max_rows == 2:
            self.num_first_visible_rows = 1
            self.indicate_skipped_rows = True
            self.num_last_visible_rows = 0
        elif max_rows == 1:
            self.num_first_visible_rows = 0
            self.indicate_skipped_rows = True
            self.num_last_visible_rows = 0
        else:
            self.num_first_visible_rows = 0
            self.indicate_skipped_rows = False
            self.num_last_visible_rows = 0

        self.col_widths = [
            min(col_fmt.max_width, max(col_fmt.min_width, len(col_fmt.name)))
            for col_fmt in self.columns]

        # analyze visible rows to calculate columns widths
        first_rows = self.records[:self.num_first_visible_rows]
        if self.num_last_visible_rows == 0:
            last_rows = []
        else:
            last_rows = self.records[-self.num_last_visible_rows:]

        for row_set in [first_rows, last_rows]:
            for row in row_set:
                assert len(self.col_widths) == len(self.columns)
                for i, pos in enumerate(self.columns_map):
                    value = row[pos]
                    str_len = len(str(value))
                    if str_len > self.col_widths[i]:
                        self.col_widths[i] = min(
                            str_len, self.columns[i].max_width)

        self.width = sum(w for w in self.col_widths) + len(self.col_widths) + 1
        self.height = self.num_first_visible_rows + self.num_last_visible_rows
        if self.indicate_skipped_rows:
            self.height += 1

    def gen_screen_lines(self) -> Iterator[str]:
        """Generate lines to be printed.

        Screen length of each line is exactly self.width. (len of
        some of generated lines may be greater because of not printable
        color sequences)
        """
        for ctext in self._gen_screen_colored_text():
            yield str(ctext)

    def _gen_screen_colored_text(self) -> Iterator[ColoredText]:
        # implementation of gen_screen_lines(), but yields ColoredText
        # instead of strings.

        if not self.col_widths:
            return  # hmm, table is absolutely empty, no columns at all!

        sep = self._COLOR_BORDER('|')

        # 1. make first border line
        border_line = self._COLOR_BORDER(
            "".join("+" + "-"*width for width in self.col_widths) + "+"
        )
        yield border_line

        # 2. table name
        line = sep + self._make_cell_text(
            self.name, self.width - 2, True) + sep
        yield line

        # 3. column names
        line = sep + sep.join(
            self._make_cell_text(col.name, width, is_header=True)
            for col, width in zip(self.columns, self.col_widths)
        ) + sep
        yield line

        # 4. one more border line
        yield border_line

        # 5. first visible records
        for row in self.records[:self.num_first_visible_rows]:
            line = sep + sep.join(
                self._make_cell_text(row[pos], width)
                for pos, width in zip(self.columns_map, self.col_widths)
            ) + sep
            yield line

        # 6. indicator of skipped lines
        if self.indicate_skipped_rows:
            yield sep + self._make_cell_text(
                "...", self.width - 2, is_warn=True) + sep

        # 7. last visible lines
        if self.num_last_visible_rows != 0:
            for row in self.records[-self.num_last_visible_rows:]:
                line = sep + sep.join(
                    self._make_cell_text(row[pos], width)
                    for pos, width in zip(self.columns_map, self.col_widths)
                ) + sep
                yield line

        # 8. final border line
        yield border_line

        # 9. total line
        yield self._make_cell_text(f"Total {len(self.records)} records.", self.width)

    def _make_cell_text(self, value, width, is_header=False, is_warn=False):
        if is_header:
            fmt = self._COLOR_NAME
            align_left = True
        elif is_warn:
            fmt = self._COLOR_WARN
            align_left = True
        elif isinstance(value, (int, float)):
            fmt = self._COLOR_NUMBER
            align_left = False
        elif value in (True, False, None):
            fmt = self._COLOR_KEYWORD
            align_left = False
        else:
            fmt = ColorFmt.get_nocolor_fmt()
            align_left = True

        plain_text = str(value)

        filler_len = width - len(plain_text)
        if filler_len < 0:
            filler_len = 0
            dots_len = min(3, width)
            visible_text_len = max(width - 3, 0)
            text = fmt(plain_text[:visible_text_len])
            text += self._COLOR_WARN('.'*dots_len)
        elif filler_len:
            filler = ColorFmt.get_nocolor_fmt()(" "*filler_len)
            if align_left:
                text = fmt(plain_text) + filler
            else:
                text = filler + fmt(plain_text)
        else:
            text = fmt(plain_text)

        return text
