"""Library of FieldType objects.

To be used when constructing tables and record formatters.
- PPDateTimeFieldType - to be used for date/time fields
- PPEnumFieldType - to be used for enum fields
"""

from datetime import datetime

from ak.color import CHText, ConfColor
from ak.ppobj import FieldType


#########################
# Common Field Types


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

    def __init__(self):
        super().__init__()

    def make_desired_cell_ch_chunks(
        self, value, fmt_modifier, fld_cp,
    ) -> ([CHText.Chunk], int):
        fmt_modifier = fmt_modifier or 'DT'
        self._verify_fmt_modifier(fmt_modifier)

        if value is None:
            return super().make_desired_cell_ch_chunks(
                value, None, fld_cp)

        assert isinstance(value, datetime)

        if fmt_modifier == 'D':
            val = [fld_cp.text(value.strftime("%Y-%m-%d"))]
        elif fmt_modifier == 'DT' or fmt_modifier == 'Dt':
            val = [fld_cp.text(value.strftime("%Y-%m-%d"))]
            if not self._is_date(value):
                time_fmt = fld_cp.warn if fmt_modifier == 'DT' else fld_cp.text
                val.append(fld_cp.warn(value.strftime(" %H:%M:%S.%f%z")))
        elif fmt_modifier == 'S':
            val = [fld_cp.text(value.strftime("%Y-%m-%d %H:%M:%S%z"))]
        else:
            val = [fld_cp.text(value.strftime("%Y-%m-%d %H:%M:%S.%f%z"))]

        return val, self.ALIGN_LEFT

    @staticmethod
    def _is_date(dt) -> bool:
        # checks if datetime object contains only the 'date' part
        return (
            dt.hour == 0 and dt.minute == 0
            and dt.second == 0 and dt.microsecond == 0)


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
        self, value, fmt_modifier, fld_cp,
    ) -> ([CHText.Chunk], int):
        """value -> desired text and alignment"""

        cache_key = id(fld_cp)  # need to maintain separate caches
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
                value, fld_cp, by_fmt_cache)

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
