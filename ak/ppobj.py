"""Methods for pretty-printing tables and json-like python objects.

Classes provided by this module:
- PPJson - pretty-printable json-like structures
- PPTable - pretty-printable 2-D tables
"""

from typing import Iterator
from ak.color import ColorFmt, ColoredText, Palette

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
                oneline_fmt = offset + scr_len < 200  # not exactly correct, ok
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

class PPTableFieldType:
    """Describe specific field in table records.

    Actual column of of PPTable corresponds to a records field, (f.e. some
    column displays 'name' of records), the way information is displayed
    depends on PPTableFieldType associated with this field.
    """
    _DUMMY_PALETTE = Palette({})  # used in default get_cell_text_len

    def __init__(self, min_width=1, max_width=999):
        self.min_width = min_width
        self.max_width = max_width

    def get_cell_text_len(self, value, fmt_modifier):
        """Calculate length of text representation of the value.

        This implementation is general, but not efficient. Override in
        derived classes to avoid construction of ColoredText objects - usually
        it is not required to find out text length.
        """
        # caluculate text length w/o constructing ColoredText object for the cell
        # return len(str(value))
        text, _ = self.make_desired_text(value, fmt_modifier, self._DUMMY_PALETTE)
        return len(ColoredText.strip_colors(str(text)))

    def make_desired_text(self, value, fmt_modifier, palette) -> (ColoredText, bool):
        """Returns desired text for a value and alignment.

        Implementation for general field type: value printed almost as is.
        To be overiden in derived classes.
        """
        if isinstance(value, (int, float)):
            syntax_name = "NUMBER"
            align_left = False
        elif value in (True, False, None):
            syntax_name = "KEYWORD"
            align_left = False
        else:
            syntax_name = None
            align_left = True
        fmt = palette.get_color(syntax_name)
        text = fmt(str(value))
        return text, align_left

    def make_cell_text(self, value, fmt_modifier, width, palette) -> ColoredText:
        """value -> ColoredText having exactly specified width."""
        text, align_left = self.make_desired_text(value, fmt_modifier, palette)
        return self._fit_to_width(text, width, align_left, palette)

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
    def _fit_to_width(text, width, align_left, palette) -> ColoredText:
        # add spaces or truncate the text so that resulting screen length of
        # ColoredText is exactly 'width' characters.
        assert width >= 0
        filler_len = width - len(text)
        if filler_len == 0:
            return text  # lucky, the text has exactly necessary length
        if filler_len > 0:
            filler = palette.get_color(None)(' '*filler_len)
            if align_left:
                return text + filler
            return filler + text
        # text is longer than necessary. It will be truncated.
        # "some long text" -> "some lo..."
        dots_len = min(3, width)
        visible_text_len = width - dots_len
        return text[:visible_text_len] + palette.get_color("WARN")('.'*dots_len)


class _PPTDefaultFieldType(PPTableFieldType):
    # implements more efficient implementation of get_cell_text_len

    def get_cell_text_len(self, value, _fmt_modifier):
        """Calculate length of text representation of the value."""
        # caluculate text length w/o constructing ColoredText object for the cell
        return len(str(value))


class PPTableField:
    """Describes possible source of data for a column of PPTable.

    F.e. user wants to display an additional column in table. He specifies
    that new column should display 'status' of the object. In this case 'status'
    corresponds to PPTableField object, which specifies position of corresponding
    value in the actual record and PPTableFieldType.

    Table can have several (or none) actual columns corresponding to the same field.

    Several (or none) fields may correspond to the same value in data record.
    F.e. two fields may correspond the same numeric value of status, but these
    fields have different PPTableFieldType, so the columns corresponding to these
    fields may display the status differently: either a simple number or
    a name from corresponding enum.
    """

    def __init__(self, name, rec_attr_pos, field_type,
                 min_width=None, max_width=None):

        assert rec_attr_pos is not None

        self.name = name
        self.field_type = field_type
        self.rec_attr_pos = rec_attr_pos
        self.min_width = min_width if min_width is not None else field_type.min_width
        self.max_width = max_width if max_width is not None else field_type.max_width


class PPTableColumn:
    """Column of a PPTable."""

    def __init__(self, name, field_type, fmt_modifier,
                 rec_attr_pos, min_width, max_width):
        self.name = name
        self.field_type = field_type

        self.field_type._verify_fmt_modifier(fmt_modifier)
        self.fmt_modifier = fmt_modifier

        self.rec_attr_pos = rec_attr_pos  # position of the field in record
        self.min_width = min_width
        self.max_width = max_width
        self.width = None  # actual width of the column, will be calculated later

    def clone(self):
        """Clone self. (except for 'width' attribute)"""
        return PPTableColumn(
            self.name,
            self.field_type,
            self.fmt_modifier,
            self.rec_attr_pos,
            self.min_width,
            self.max_width,
        )

    @classmethod
    def from_fmt_str(cls, col_fmt, fields_by_name):
        """Create PPTableColumn object from format string."""
        # col_fmt examples: "id:10-25(15)", "user_uuid/short:25"
        # "field_name/format_modifier:min_w-max_w(cur_w)"
        # cur_w part is ignored - Allow it to be present to make it
        # possible to set new fmt string in a format it was reported.

        # 1.1. find field name
        chunks = col_fmt.split(":")
        if len(chunks) > 2:
            raise ValueError(f"Invalid column format: '{col_fmt}'")
        elif len(chunks) == 2:
            # fmt looks like "name:5-15"
            field_name, width_fmt = chunks
        else:
            # fmt is just a field name
            field_name = col_fmt
            width_fmt = ""

        fmt_modifier = None
        br_pos = field_name.find('/')
        if br_pos >= 0:
            # field name includes format modifier. Like this: "user_uuid/short"
            fmt_modifier = field_name[br_pos+1:]
            field_name = field_name[:br_pos]

        if field_name not in fields_by_name:
            raise ValueError(
                f"Unknown field '{field_name}' specified. "
                f"Available fields: {fields_by_name.keys()}.")
        field = fields_by_name[field_name]

        # 1.2. ignore the optional current actual width
        br_pos = width_fmt.find('(')
        if br_pos >= 0:
            width_fmt = width_fmt[:br_pos]

        # 1.3. parse width limits
        # It may be either a number or range
        if not width_fmt:
            min_width = field.min_width
            max_width = field.max_width
        else:
            chunks = width_fmt.split('-')
            if len(chunks) > 2:
                raise ValueError(f"Invalid width range: '{width_fmt}'")
            widths = []
            for w in chunks:
                try:
                    widths.append(int(w))
                except ValueError as err:
                    raise ValueError(
                        f"Invalid width '{w}' specified for field {field_name}"
                    ) from err
            if len(widths) > 1:
                min_width, max_width = widths
            else:
                min_width = widths[0]
                max_width = min_width

        return PPTableColumn(
            field.name,
            field.field_type,
            fmt_modifier,
            field.rec_attr_pos,
            min_width,
            max_width,
        )

    def to_fmt_str(self):
        """Create fmt string - human readable and editable descr of self."""
        fmt_str = self.name
        if self.fmt_modifier is not None:
            fmt_str += f"/{self.fmt_modifier}"

        if self.min_width == self.max_width:
            fmt_str += f":{self.min_width}"
        else:
            fmt_str += f":{self.min_width}-{self.max_width}"
            if self.width is not None:
                fmt_str += f"({self.width})"

        return fmt_str


class PPTableFormat:
    """Contains information about PPTable format: visible columns, etc."""

    _DFLT_FIELD_TYPE = _PPTDefaultFieldType()

    def __init__(self, fmt, *, other=None, fields=None, sample=None,
                 field_types=None):
        """Constructor of PPTableFormat.

        Arguments:
        - fmt: string, which describes format of the table (*)
        - other: (optional) other PPTableFormat object to get details from
        - fields: (optional) one of:
            - list of names of fields (these names must correspond to the
              order of attributes of actual records).
            - list of PPTableField objects.
        - sample: (optional) sample record to get information about fields from
        - field_types: (optional) {field_name: PPTableFieldType}. Can be used
          to specify types of newly constructed fields.

        (*) New PPTableFormat is created according to 'fmt' description
        either 'from scratch' (if 'fields' or 'sample' arg specified) or from
        existing 'other' PPTableFormat object.

        'fmt' string consists of 3 parts separated by ';'. These parts are
        1. visible columns description
        2. record limits description
        3. total table width (not implemented)

        Special values for each part are:
        "" - keep format as in 'other' or create default
        "*" - "show all"

        1. visible columns description describes columns of the table. Example:

            "field_1:7, field_2:5-20" - two columns, width of first is fixed, width
              of the second must be in range [5-20].

        2. record limits example:

            "10-15" - if number of records is more that 26, only 10 first and
              15 last records will be displayed.
        """
        self.fields = self._make_fields_list(other, fields, sample, field_types)
        self.fields_by_name = {}  # {field_name: (field, rec_attr_pos)}
        for f in self.fields:
            if f.name in self.fields_by_name:
                raise ValueError(
                    f"Duplicate field name '{f.name}': {self.fields}")
            self.fields_by_name[f.name] = f

        self.columns = None
        self.n_first = None
        self.n_last = None
        self.ns_are_default = True
        self._init_self_with_fmt(fmt, other)
        assert self.columns is not None

    def __repr__(self):
        # it's important that repr contains fmt string, which can be used
        # to construct new format objects
        return self._get_fmt_str()

    def __str__(self):
        return self._get_fmt_str()

    @classmethod
    def _make_fields_list(cls, other, fields, sample, field_types):
        # first step of constructor: create list of fields from one
        # of available sources
        if other is not None:
            # just get fields from the other
            assert fields is None
            assert sample is None
            assert field_types is None
            return other.fields

        if fields is not None:
            assert sample is None
            assert isinstance(fields, (list, tuple))

            if all(isinstance(f, PPTableField) for f in fields):
                # fields is a ready list of PPTableField objects
                assert field_types is None
                return fields

            # fields is a list of names of fields
            assert all(isinstance(f, str) for f in fields)
            fields_names = fields
        else:
            assert sample is not None
            assert hasattr(sample, "_fields"), (
                f"can't create fields list from sample record {sample} "
                f"(type {str(type(sample))}). The sample is usually a "
                f"namedtuple and should have a '_fields' attribute")
            fields_names = sample._fields

        # now fields_names is a list of names of fields, in the order as they
        # are present in actual data record
        assert isinstance(fields_names, (list, tuple))
        if field_types is None:
            field_types = {}

        fields = [
            PPTableField(
                name, pos,
                field_types.get(name, cls._DFLT_FIELD_TYPE)
            ) for pos, name in enumerate(fields_names)]

        return fields

    def _init_self_with_fmt(self, fmt, other):
        # final step of construction, to be called from constructor only

        fmt_s_cols, fmt_s_recs, fmt_s_twidths = self._fmt_str_split(fmt)

        # part 1: format of visible columns
        self._set_fmt_cols(fmt_s_cols, other)

        # part 2: format of visible rows
        try:
            self._set_fmt_vis_recs(fmt_s_recs, other)
        except ValueError as err:
            raise ValueError(
                f"Invalid specification of numbers of visible lines: "
                f"'{fmt_s_recs}'. Expected 'n_first:n_last' or '*' or empty str."
            ) from err

        # part 3: total width of the table
        # not implemented yet
        _ = fmt_s_twidths

    def _get_fmt_str(self):
        # create the 'fmt' string which describes self.

        parts = []
        # 1. format of visible columns
        parts.append(",".join(c.to_fmt_str() for c in self.columns))

        # 2. numbers of visible lines
        if self.ns_are_default:
            parts.append("")
        elif self.n_first is None or self.n_last is None:
            parts.append("*")
        else:
            parts.append(f"{self.n_first}:{self.n_last}")

        # 3. format max table width
        # not implemented

        while parts and parts[-1] == "":
            parts.pop()

        return ";".join(parts)

    def _set_fmt_cols(self, fmt_s_cols, other):
        # apply part 1 (visible columns) of 'fmt' to self.
        if fmt_s_cols == "":
            if other is not None:
                # clone columns form the other
                self.columns = [c.clone() for c in other.columns]
                return
            else:
                fmt_s_cols = "*"

        if fmt_s_cols == "*":
            # default: show all columns
            self.columns = [
                PPTableColumn(
                    f.name, f.field_type, None,
                    f.rec_attr_pos, f.min_width, f.max_width,
                ) for f in self.fields]
            return

        self.columns = [
            PPTableColumn.from_fmt_str(part.strip(), self.fields_by_name)
            for part in fmt_s_cols.split(",")
        ]

    def _set_fmt_vis_recs(self, fmt_s_recs, other):
        # apply part 2 (records limits) of 'fmt' to self.
        if fmt_s_recs == "":
            if other is not None:
                self.n_first = other.n_first
                self.n_last = other.n_last
                self.ns_are_default = other.ns_are_default
            else:
                self.n_first = 20
                self.n_last = 10
                self.ns_are_default = True
        elif fmt_s_recs == "*":
            self.n_first = None
            self.n_last = None
            self.ns_are_default = False
        else:
            # "20:10" - show 20 first recs and 15 last recs
            parts = [x.strip() for x in fmt_s_recs.split(':')]
            if len(parts) != 2:
                raise ValueError(f"{len(parts)} parts")
            self.n_first, self.n_last = [int(x) for x in parts]
            self.ns_are_default = False

    @staticmethod
    def _fmt_str_split(fmt_str):
        # constructor helper: split 'fmt' string into parts
        if fmt_str is None:
            fmt_str = ";;"
        parts = fmt_str.split(';')
        if len(parts) > 3:
            raise ValueError(f"Invalid fmt string '{fmt_str}'")

        while len(parts) < 3:
            parts.append("")  # "" format means "no need to change anything"

        return parts


class PPTable(PPObj):
    """2-D table.

    Provides pretty-printing and simple manipulation on 2-D table
    of data (such as results of sql query).
    """

    class _ServiceCells(PPTableFieldType):
        # used to format columns name cells, etc.
        def make_title_text(self, value, width, palette) -> ColoredText:
            """Is used to format columns names cells and table title"""
            assert isinstance(value, str), f"{value} is {type(value)}"
            fmt = palette.get_color("NAME")
            return self._fit_to_width(fmt(value), width, True, palette)

        def make_summary_text(self, summary, width, palette) -> ColoredText:
            """Is used to format table summary"""
            assert isinstance(summary, (str, ColoredText))
            if not isinstance(summary, ColoredText):
                fmt = palette.get_color(None)
                summary = fmt(summary)
            return self._fit_to_width(summary, width, True, palette)

    def __init__(
            self, records, *,
            header=None,
            footer=None,

            fmt=None,
            fmt_obj=None,
            fields=None,
            sample=None,
            field_types=None,
    ):
        """PPTable constructor.

        Arguments:
        - records: list of records (record is a tuple of values, corresponding
          to a row of the table)
        - header: (optional), str or ColoredText. Description of the table, will
            be prited as header. Special values:
            - None (default) - description will be created automatically
            - "" - description will not be created and printed
        - footer: (optional), str or ColoredText. Table footer. Special values:
            - None (default) - footer will be created automatically
            - "" - footer will not be created and printed.

        Arguments for PPTableFormat:
        - fmt, fmt_obj, fields, fields, sample, field_types: correspond to
          arguments of PPTableFormat constructor. Check doc of
          ak.ppobj.PPTableFormat for more details.
        """
        self.records = records
        self.r = records

        self._ppt_fmt = PPTableFormat(
            fmt,
            other=fmt_obj, fields=fields, sample=sample, field_types=field_types)

        if header is None:
            header = "some table"
        self._header = header

        if footer is None:
            footer = f"Total {len(self.records)} records"
        self._footer = footer

        self.palette = Palette({
            'TBL_BORDER': ColorFmt('GREEN'),
            'NAME': ColorFmt('GREEN', bold=True),
            'NUMBER': ColorFmt('YELLOW'),
            'KEYWORD': ColorFmt('BLUE', bold=True),
            'WARN': ColorFmt('RED'),
        })

    def set_fmt(self, fmt):
        """Specify fmt - a string which describes format of the table.

        Method returns self - so that in python console the modified table be
        printed out immediately.
        """
        self._ppt_fmt = PPTableFormat(fmt, other=self._ppt_fmt)
        return self

    def _get_fmt(self):
        # getter of 'fmt' property.
        # returns PPTableFormat object
        # repr of this object contains fmt string which can be used to apply
        # new format
        return self._ppt_fmt

    fmt = property(_get_fmt, set_fmt)

    def gen_pplines(self) -> Iterator[str]:
        # implementation of PrettyPrinter functionality
        for line in self._gen_ppcolored_text():
            yield str(line)

    def _gen_ppcolored_text(self) -> Iterator[ColoredText]:
        # generate ColoredText objects - lines of the printed table

        columns = self._ppt_fmt.columns

        n_first = self._ppt_fmt.n_first
        n_last = self._ppt_fmt.n_last
        if (n_first is not None
            and n_last is not None
            and len(self.records) > n_first + n_last + 1
           ):
            n_skipped = len(self.records) - n_first - n_last
        else:
            # show all records
            n_first = len(self.records)
            n_last = 0
            n_skipped = 0

        assert n_first >= 0 and n_last >= 0 and n_skipped >= 0
        head_recs = self.records[:n_first] if n_first else []
        foot_recs = self.records[-n_last:] if n_last else []

        # calculate actual widths of table columns
        # process only columns w/o specified width
        for col in columns:
            if col.min_width == col.max_width:
                col.width = col.min_width
            else:
                col.width = min(
                    col.max_width, max(col.min_width, len(col.name)))

        cols = [col for col in columns if col.min_width != col.max_width]
        desired_widths = [len(col.name) for col in cols]
        for recs in (head_recs, foot_recs):
            for rec in recs:
                for i, col in enumerate(cols):
                    value = rec[col.rec_attr_pos]
                    desired_widths[i] = max(
                        desired_widths[i], col.field_type.get_cell_text_len(
                            value, col.fmt_modifier))

        for desired_width, col in zip(desired_widths, cols):
            col.width = min(
                col.max_width, max(col.min_width, desired_width))

        table_width = sum(col.width for col in columns) + len(columns) + 1

        border_color = self.palette.get_color("TBL_BORDER")
        sep = border_color('|')
        service_cells_formatter = self._ServiceCells()

        # 1. make first border line
        border_line = border_color(
            "".join("+" + "-"*col.width for col in columns) + '+')
        yield border_line

        # 2. table title
        if self._header:
            line = sep + service_cells_formatter.make_title_text(
                self._header,
                table_width - 2,
                self.palette) + sep
            yield line

        # 3. column names
        line = sep + sep.join(
            service_cells_formatter.make_title_text(
                col.name, col.width, self.palette)
            for col in columns
        ) + sep
        yield line

        # 4. one more border_line
        yield border_line

        # 5. first visible records
        for rec in head_recs:
            yield self._make_table_line(rec, columns, sep, self.palette)

        # 6. indicator of skipped lines
        if n_skipped:
            line = sep + service_cells_formatter.make_summary_text(
                self.palette.get_color("WARN")("... ") +
                self.palette.get_color(None)(f"{n_skipped} records skipped"),
                table_width - 2,
                self.palette,
            ) + sep
            yield line

        # 7. last visible records
        for rec in foot_recs:
            yield self._make_table_line(rec, columns, sep, self.palette)

        # 8. final border line
        yield border_line

        # 9. summary line
        if self._footer:
            yield service_cells_formatter.make_summary_text(
                self._footer,
                table_width,
                self.palette)

    def _make_table_line(self, record, columns, sep, palette):
        # create ColoredText - representaion of a single record in table
        line = sep + sep.join(
            col.field_type.make_cell_text(
                record[col.rec_attr_pos],  # value
                col.fmt_modifier,
                col.width, palette)
            for col in columns
        ) + sep
        return line


#########################
# PPEnumFieldType

class PPEnumFieldType(PPTableFieldType):
    """PPTable Enum Field Type.

    Generates values for PPTable cells, f.e.: "10 Active"
    """
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
        self.enum_missing_value = enum_values.get(self.MISSING, ("<???>", "ERR"))

        self.max_val_len = max(
            (len(str(x)) for x in self.enum_values if x is not None),
            default=1)

        self._cache = {}  # {palette_id: {fmt_modifier: {enum_val: (text, align)}}}
        self._cache_lengths = {
            fmt_modifier: {}
            for fmt_modifier in self._FMT_MODIFIERS
        }  # {fmt_modifier: {enum_val: length}}
        self._cache_lengths[None] = self._cache_lengths['full']
        super().__init__()

    def make_desired_text(self, value, fmt_modifier, palette) -> (ColoredText, bool):
        """Returns desired text for a value and alignment."""

        # prepare and cache cell text for a enum value
        # cache is prepared for all supported format modifiers
        try:
            by_fmt_cache = self._cache[id(palette)]
        except KeyError:
            by_fmt_cache = self._cache[id(palette)] = {
                fmt_modifier: {}
                for fmt_modifier in self._FMT_MODIFIERS
            }
            # None and 'full' format modifiers will refer to the same cached vals
            by_fmt_cache[None] = by_fmt_cache['full']
            self._cache[id(palette)] = by_fmt_cache

        by_value_cache = by_fmt_cache.get(fmt_modifier, None)
        if by_value_cache is None:
            self._verify_fmt_modifier(fmt_modifier)

        if value not in by_value_cache:
            self._make_text_cache_for_val(value, palette, by_fmt_cache)

        return by_value_cache[value]

    def _make_text_cache_for_val(self, value, palette, by_fmt_cache):
        # populate self._cache for value
        # ('by_fmt_cache' is part of self._cache)
        try:
            name, syntax_name = self.enum_values[value]
            val_len = self.max_val_len
        except KeyError:
            if value is None:
                # special case: cell will not contain enum's value and name,
                # but a single None
                text_ang_alignment = super().make_desired_text(value, None, palette)
                by_fmt_cache['val'][value] = text_ang_alignment
                by_fmt_cache['name'][value] = text_ang_alignment
                by_fmt_cache['full'][value] = text_ang_alignment
                return
            name, syntax_name = self.enum_missing_value
            val_len = max(self.max_val_len, len(str(value)))

        # 'val' format
        val_text, align = super().make_desired_text(value, None, palette)
        by_fmt_cache['val'][value] = (val_text, align)

        # 'name' format
        fmt = palette.get_color(syntax_name)
        name_text = fmt(name)
        by_fmt_cache['name'][value] = (name_text, align)

        # 'full' format
        prefix_pad = ""
        pad_len = val_len - len(val_text)
        if pad_len > 0:
            # align 'value' portion of the text to right
            prefix_pad = " " * pad_len
        full_text = ColoredText(prefix_pad, val_text, " ", name_text)
        by_fmt_cache['full'][value] = (full_text, True)

    def get_cell_text_len(self, value, fmt_modifier):
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

    def is_fmt_modifier_ok(self, fmt_modifier):
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
