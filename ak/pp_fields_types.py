"""Library of FieldType objects.

To be used when constructing tables and record formatters.
- PPTitleFieldType - field type which formats values for column titles
- PPDateTimeFieldType - to be used for date/time fields
- PPEnumFieldType - to be used for enum fields
- MatrixFieldValueType - to be used when values of different types are supposed
    to be present in the same table column

Note, that above-mentioned objects are classes. When constructing a table you
need to specify an instance of FieldType class. In most cases it is possible to
use already created instances of these objects:
- title_field_type
- date_time_field_type
"""

from datetime import datetime

from ak.color import CHText, ConfColor
from ak.ppobj import FieldType, FieldValueType, _DefaultTitleFieldType


#########################
# Common Field Types

# PPTitleFieldType - format values the same way as for columns titles

PPTitleFieldType = _DefaultTitleFieldType
title_field_type = _DefaultTitleFieldType()


# PPDateTimeFieldType - format dates and time values

class PPDateTimeFieldType(FieldType):
    """FieldType for representing date/time values.

    Several predefined formats are supported (see _FMT_MODIFIERS)
    """

    _FMT_MODIFIERS = {
        'D': "print only date part: YYYY-MM-DD",
        'Dt': "Prints date, prints time part if it is present",
        'DT': "Same as 'Dt', but prints time part in alternative color (as warning)",
        'S': "use YYYY-MM-DD HH:MM:SS, include timezone info if present",
        'MS': "use YYYY-MM-DD HH:MM:SS.ffffff, include timezone info if present",
    }

    def make_desired_cell_ch_chunks(
        self, value, fmt_modifier, cell_plt,
    ) -> ([CHText.Chunk], int):
        fmt_modifier = fmt_modifier or 'DT'
        self._verify_fmt_modifier(fmt_modifier)

        if value is None:
            return super().make_desired_cell_ch_chunks(
                value, None, cell_plt)

        assert isinstance(value, datetime)

        if fmt_modifier == 'D':
            val = [cell_plt.text(value.strftime("%Y-%m-%d"))]
        elif fmt_modifier == 'DT' or fmt_modifier == 'Dt':
            val = [cell_plt.text(value.strftime("%Y-%m-%d"))]
            if not self._is_date(value):
                time_fmt = cell_plt.warn if fmt_modifier == 'DT' else cell_plt.text
                val.append(cell_plt.warn(value.strftime(" %H:%M:%S.%f%z")))
        elif fmt_modifier == 'S':
            val = [cell_plt.text(value.strftime("%Y-%m-%d %H:%M:%S%z"))]
        else:
            val = [cell_plt.text(value.strftime("%Y-%m-%d %H:%M:%S.%f%z"))]

        return val, self.ALIGN_LEFT

    @staticmethod
    def _is_date(dt) -> bool:
        # checks if datetime object contains only the 'date' part
        return (
            dt.hour == 0 and dt.minute == 0
            and dt.second == 0 and dt.microsecond == 0)


date_time_field_type = PPDateTimeFieldType()


# PPEnumFieldType - format enums

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
        self, value, fmt_modifier, cell_plt,
    ) -> ([CHText.Chunk], int):
        """value -> desired text and alignment"""

        cache_key = id(cell_plt)  # need to maintain separate caches
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
                value, cell_plt, by_fmt_cache)

        return by_value_cache[value]

    def _make_text_cache_for_val(self, value, cell_plt, by_fmt_cache) -> None:
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
                    value, None, cell_plt)
                by_fmt_cache['val'][value] = text_and_alignment
                by_fmt_cache['name'][value] = text_and_alignment
                by_fmt_cache['full'][value] = text_and_alignment
                return
            name, syntax_name = self.enum_missing_value
            val_len = max(self.max_val_len, len(str(value)))

        color_fmt = cell_plt.get_color(syntax_name)

        # 'val' format
        val_text_items, align = super().make_desired_cell_ch_chunks(
            value, None, cell_plt)
        by_fmt_cache['val'][value] = (val_text_items, align)

        # 'name' format
        by_fmt_cache['name'][value] = ([color_fmt(name)], align)

        # 'full' format
        full_text_items = []
        pad_len = val_len - CHText.calc_chunks_len(val_text_items)
        if pad_len > 0:
            # align 'value' portion of the text to right
            full_text_items.append(cell_plt.text(" " * pad_len))
        full_text_items.extend(val_text_items)
        full_text_items.append(cell_plt.text(" "))
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


#########################
# MatrixFieldValueType

class MatrixFieldValueType(FieldValueType):
    """Field Value, which is formatted using specified FieldType.

    Example: a table with two columns, "name" and "value".
    Different values in "value" column may have different types: strings, numbers,
    dates, custom types, etc. To properly format all these values we may use
    instances of FieldValueType-derived class as the values and associate the
    default FieldType with this column. In this case the value itself will produce
    the formatted text.

    MatrixFieldValueType is an implementation of FieldValueType which formats
    the value using specified FieldType.
    """

    def __init__(self, value, field_type, fmt_modifier=None):
        assert not isinstance(field_type, type), (
            f"invalid field_type argument. Expected instance of FieldType, got "
            f"a class object: {field_type}")
        self.value = value
        self.field_type = field_type
        self.fmt_modifier = fmt_modifier

    def make_desired_cell_ch_chunks(
        self, fmt_modifier, cell_plt,
    ) -> ([CHText.Chunk], int):
        """make desired text and alignment for self.value and self.field_type"""
        cell_plt = cell_plt.get_sub_palette(self.field_type.PALETTE_CLASS)

        # value of the 'fmt_modifier' argument was specified in the record or table
        # description of current column. In case of the matrix field the values
        # in the column may be be of different types and have different possible
        # values of fmt_modifier. The fmt_modifier specified for the whole column
        # can not be used for individual cell. The fmt_modifier for this particular
        # cell is specified in self:

        return self.field_type.make_desired_cell_ch_chunks(
            self.value, self.fmt_modifier, cell_plt)
