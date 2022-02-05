"""Convert data present in excel tables into python objects.

This module reads data from excel workbooks open with openpyxl package

Example:

# create a data calss
class XlPerson(XlsObject):
    _ATTRS = ['id', 'name', 'status']
    _NUM_ID_ATTRS = 1

# transform data from excel worksheet into XlPerson objects
people = list(read_table(wb['sheet1'], XlPerson, {
    'id': ('Id', cell_int),
    'name': ("Person's name", cell_str),
    'status': ('Status', cell_int),
}))
"""


#########################
# Cell Types - objects that convert excel cell to simple value

class _CellReader:
    _NONE_VALUES = {None}

    def __init__(self, none_values=None):
        self.none_values = (
            set(none_values) if none_values is not None else self._NONE_VALUES)

    def val_from_cell(self, cell):
        """xls cell -> optional string value of the cell"""
        if cell.value in self.none_values:
            return None
        return self._make_value(cell)

    def _make_value(self, _cell):
        assert False, "pure virtual"


class CellStr(_CellReader):
    """Get string value from cell."""
    def _make_value(self, cell):
        v = cell.value
        return "" if v is None else str(v).strip()


class CellInt(_CellReader):
    """Get int value from cell."""
    def _make_value(self, cell):
        v = cell.value
        if not isinstance(v, int):
            raise ValueError(f"cell {cell} contains not an integer value {v}")
        return v


class CellBool(_CellReader):
    """Gets bool value from cell"""

    _TRUE_VALUES = set(['v', 1, '1', True, 'True'])
    _FALSE_VALUES = set([None, '', False, 'False'])
    _NONE_VALUES = []

    def __init__(self, true_values=None, false_values=None, none_values=None):
        self.true_values = (
            set(true_values) if true_values is not None else self._TRUE_VALUES)
        self.false_values = (
            set(false_values) if false_values is not None else self._FALSE_VALUES)
        if none_values is None:
            none_values = self._NONE_VALUES
        super().__init__(none_values)

    def _make_value(self, cell):
        v = cell.value
        if v in self.true_values:
            return True
        if v in self.false_values:
            return False
        raise ValueError(
            f"value of cell {cell} is not valid bool value: {cell.value}")


class CellList(_CellReader):
    """Gets list of strings value from cell.

    Cell supposed to contain a list of values separated by ',' and/or new line.
    Empty elements are ignored.
    """

    def _make_value(self, cell):
        # xls cell -> list of strings value of the cell
        v = cell.value
        if not hasattr(v, 'split'):
            raise ValueError(
                f"cell {cell} does not contain a list of values. "
                f"The cell contains {type(v).__name__}: '{v}'")
        vals = [item.strip() for item in v.replace('\n', ',').split(',')]
        vals = [item for item in vals if item]
        return vals


class _CellRangeReader:
    # base class for 'range cells readers'
    __slots__ = ('cell_type', )
    def __init__(self, cell_type):
        self.cell_type = cell_type

    def val_from_cells(self, _cells_titles, _cells):
        """range of cells -> value. To be implemented in derived classes."""
        assert False, "pure virtual"


class CellRangeDict(_CellRangeReader):
    """Make a dictionary of values from range of excel cells"""
    def val_from_cells(self, cells_titles, cells):
        """range of cells -> {column_title: cell_value}."""
        assert len(cells_titles) == len(cells)
        val = {
            title: self.cell_type.val_from_cell(cell)
            for title, cell in zip(cells_titles, cells)
        }
        attr_origins = {
            cell_title: cell.coordinate
            for cell_title, cell in zip(cells_titles, cells)
        }
        return val, attr_origins


class CellRangeSet(_CellRangeReader):
    """Make a set of values from range of excel cells"""
    def val_from_cells(self, cells_titles, cells):
        """Range of cells -> set(column_title of marked cells)."""
        assert len(cells_titles) == len(cells)
        val = {
            title
            for title, cell in zip(cells_titles, cells)
            if self.cell_type.val_from_cell(cell)
        }
        attr_origins = {
            cell_title: cell.coordinate
            for cell_title, cell in zip(cells_titles, cells)
        }
        return val, attr_origins


#########################
# XlsObject

class XlsObject:
    """Base class for objects to be read from excel worksheet.

    Main purpose of XlsObject is to remember addresses of excel cells,
    from which the object was created.
    """

    _ATTRS = ()  # list of attributes, which will be read from excel
    _NUM_ID_ATTRS = 0  # number of first attributes in _ATTRS, which make the
                       # logical id of the object

    __slots__ = '_src_ws_name', '_anchor_cell_coord', '_attrs_origins', 'logic_id'

    def __init__(self, cells_types, cells_list):
        assert self._NUM_ID_ATTRS <= len(self._ATTRS)
        assert len(cells_list) == len(self._ATTRS), (
            f"Can't init {type(self)}. Expected "
            f"{len(self._ATTRS)} cells, actually got {len(cells_list)} cells")

        anchor_cell = cells_list[0]
        self._src_ws_name = anchor_cell.parent.title
        if ' ' in self._src_ws_name:
            self._src_ws_name = f"'{self._src_ws_name}'"
        self._anchor_cell_coord = anchor_cell.coordinate
        self._attrs_origins = {}

        for attr_name, cell_type, cell in zip(self._ATTRS, cells_types, cells_list):
            if hasattr(cell_type, 'val_from_cells'):
                # cell should be not a single cell, but range
                column_names, cells = cell
                val, attr_origins = cell_type.val_from_cells(column_names, cells)
            elif cell_type is None:
                # this attribute explicitely ignored by reading rules
                assert cell is None
                val = None
                attr_origins = "<skipped column>"
            elif cell is None:
                # this cell corresponds to a 'missing' column
                # it was explicitely allowed with 'column_is_optional' rule
                val = None
                attr_origins = "<skipped column>"
            else:
                val = cell_type.val_from_cell(cell)
                attr_origins = cell.coordinate
            setattr(self, attr_name, val)
            self._attrs_origins[attr_name] = attr_origins

        self.logic_id = self._compose_key_value()

    @classmethod
    def construct(cls, cells_types, cells):
        """Constructor, but may return None if cells are empty."""
        key_valls_empty = all(
            cell.value is None for cell in cells[:cls._NUM_ID_ATTRS])

        if key_valls_empty and cls._NUM_ID_ATTRS > 0:
            return None
        obj = cls(cells_types, cells)
        if cls._NUM_ID_ATTRS > 0 and obj.key_is_none():
            return None
        return obj

    def _compose_key_value(self):
        # Create a value (single value or tuple) which corresponds to
        # logic_id attributes of the object. To be used in constructor.
        key_tuple = tuple(
            getattr(self, attr_name)
            for attr_name in self._ATTRS[:self._NUM_ID_ATTRS]
        )
        return key_tuple[0] if len(key_tuple) == 1 else key_tuple

    def key_is_none(self):
        """Check if all key attributes of the object are None."""
        if self._NUM_ID_ATTRS == 1:
            return self.logic_id is None
        return all(v is None for v in self.logic_id)

    def __str__(self):
        return (
            f"<{type(self).__name__}"
            f"({self._src_ws_name} {self._anchor_cell_coord}) {self.logic_id}>")

    def get_attr_origin(self, attr_name, range_key=None, *, incl_ws=False):
        """Return coordinate of the cell(s) corresponding to attribute.

        Examples:
        - x.get_attr_origin('name') => "C10" means that x.name value was read
            from excel cell "C10"
        - x.get_attr_origin('grades') => "D13:P13" means that a.grades is a
            ranged attribute, values for it were taken from range of cells from
            "D13" to "P13"
        - x.get_attr_origin('grades', 'math') => "M13" 'ranged' attribute, the
           value  corresponding to key 'math' was read from excel cell "M13"

        Arguments:
        - attr_name: name of attribute
        - range_key: can be specified for ranged attributes
        - incl_ws: if to include worksheet name in returned cell coordinate.
        """
        ws_prefix = f"{self._src_ws_name} " if incl_ws else ""
        origins = self._attrs_origins.get(attr_name)

        if origins is None:
            if attr_name in self._ATTRS:
                return ws_prefix + "<skipped column>"
            if hasattr(self, attr_name):
                raise ValueError(
                    f"attribute '{attr_name}' does not correspond to excell cell")
            raise ValueError(f"unknown attribute '{attr_name}'")

        if isinstance(origins, str):
            # this is not a 'ranged' attribute
            if range_key is not None:
                raise ValueError(
                    f"'{attr_name}' is not a ranged attribute, "
                    f"range_key argument '{range_key}' is not applicable")
            return ws_prefix + origins

        # the attribute must be ranged
        assert isinstance(origins, dict)
        if range_key is None:
            # return description of all the source cells
            cells_coords = sorted(origins.values())
            if len(cells_coords) == 0:
                cells_range_descr = "<skipped column>"
            elif len(cells_coords) == 1:
                cells_range_descr = cells_coords[0]
            else:
                cells_range_descr = f"{cells_coords[0]}:{cells_coords[-1]}"
            return ws_prefix + cells_range_descr

        val_cell_origin = origins.get(range_key)

        if val_cell_origin is None:
            raise ValueError(
                f"ranged attribute '{attr_name}' has no key '{range_key}'")

        return ws_prefix + val_cell_origin

    def __repr__(self):
        return self.__str__()

    def ensure_equal(self, other):
        """Make sure two objects with same logic_id values are actually equal."""
        assert type(self) is type(other)
        assert self.logic_id == other.logic_id
        for attr_name in self._ATTRS:
            if getattr(self, attr_name) != getattr(other, attr_name):
                raise ValueError(
                    f"{type(self)} objects created from cells "
                    f"'{self._anchor_cell_coord}' and "
                    f"'{other._anchor_cell_coord}' have "
                    f"same logic_id value {self.logic_id} "
                    f"but different values of attribute '{attr_name}': "
                    f"{getattr(self, attr_name)} and {getattr(other, attr_name)}"
                )

    @classmethod
    def make_objects_map(cls, objects):
        """Convert sequence of XlsObject's into map by logic_id.

        Verifies that objects with same logic_id have same attributes.
        """
        d = {}
        for obj in objects:
            if obj is None:
                continue
            if obj.logic_id in d:
                obj.ensure_equal(d[obj.logic_id])
            d[obj.logic_id] = obj
        return d


#########################
# Xls Table reading rules

class XlsRecordAttrReadRules:
    """Rules of reading a single attribute from excel table."""

    def __init__(self, attr_name, column_name, cell_type, *,
                 column_is_optional=False):
        """Rules of reading a single XlsObject attribute from excel table.

        Arguments:
        - attr_name: name of the attribute
        - column_name: name of column of ecxel table. Column name should
            be '*' for 'range' values
        - cell_type: object, which converts excel cell into a simple value
            (obj of either _CellReader or _CellRangeReader -derived class)
        - column_is_optional: allow column with column_name name not to be present
            in table.
        """
        if hasattr(cell_type, 'val_from_cells'):
            assert column_name == '*'
        self.attr_name = attr_name
        self.column_name = column_name
        self.cell_type = cell_type
        self.column_is_optional = column_is_optional


class XlsObjReadRules:
    """Rules of reading an object of specified type from excel table record."""

    def __init__(self, obj_class, attrs_rules):
        """Construct rules of reading object from excel table.

        Arguments:
        - obj_class: XlsObject-derived class
        - attrs_rules: {attr_name: attr_read_rules}
            Here attr_read_rules is a rules of reading of a single attribute and
            may be:
            - None: explicit indicator that the value for the attribute should not
                be read
            - XlsRecordAttrReadRules object
            - (column_name, cell_type[, {}]) - arguments for XlsRecordAttrReadRules
        """
        self.obj_class = obj_class

        self.attrs_rules = []  # XlsRecordAttrReadRules in same order as _ATTRS
        attrs_rules_map = {}  # {attr_name: XlsRecordAttrReadRules}
        for attr_name, attr_info in attrs_rules.items():
            if attr_info is None:
                # it is explicitely stated, that value for this attr is not
                # present in excel table
                attrs_rules_map[attr_name] = XlsRecordAttrReadRules(
                    attr_name, None, None, column_is_optional=True)
                continue
            if isinstance(attr_info, XlsRecordAttrReadRules):
                attrs_rules_map[attr_name] = attr_info
                continue
            assert isinstance(attr_info, (list, tuple))
            if len(attr_info) == 2:
                column_name, cell_type = attr_info
                attr_rrules = XlsRecordAttrReadRules(
                    attr_name, column_name, cell_type)
            elif len(attr_info) == 3:
                column_name, cell_type, attr_kwargs = attr_info
                attr_rrules = XlsRecordAttrReadRules(
                    attr_name, column_name, cell_type, **attr_kwargs)
            attrs_rules_map[attr_name] = attr_rrules
        assert len(attrs_rules_map) == len(attrs_rules)

        miss_attrs = set(obj_class._ATTRS) - attrs_rules_map.keys()

        if miss_attrs:
            raise ValueError(
                f"Column names corresponding to '{str(obj_class)}' attributes "
                f"{miss_attrs} are not specified")

        self.attrs_rules = [
            attrs_rules_map[attr_name] for attr_name in self.obj_class._ATTRS]


class _ObjScrCellsMap:
    # map of XlsObject attributes to cell's ids
    def __init__(self, attrs_rules):
        self.attrs_rules = attrs_rules
        self.cells_types = [rr.cell_type for rr in self.attrs_rules]
        self.columns_map = None  # positions of columns, corresponding to attrs_rules

    def get_known_columns_names(self):
        """Return set of all column names, which correspond to object attributes.

        Note, that some columns correspond to range attributes (such columns
        do not correspond to attributes directly, values and names of several
        columns are combined into a single range attribute)
        """
        return {
            attr_rrules.column_name
            for attr_rrules in self.attrs_rules
            if attr_rrules.column_name != "*"}

    def bind_titles_row(self, cols_names, col_names_ids, known_cols_names):
        """finish construction by binding self to actual columns names.

        Arguments:
        - cols_names: list of columns named (read from excel row corresponding
            to title of the table)
        - col_names_ids: {name: int_column_position}. This is a separate argument
            for optimisation only (this map can be constructed from 'cols_names')
        - known_cols_names: set of names of columns expected by this and all other
            _ObjScrCellsMap's related to current excel table. This is required to
            detect columns which corresspond to 'range' attributes.
        """
        self.columns_map = []
        for attr_rrules in self.attrs_rules:
            if attr_rrules.column_name == "*":
                # this is 'range' attribute. It's value is taken from several cells.
                # let's detect cells corresponding to this attribute.
                #
                # for now algorithm is simple: range cells are continuous range
                # of cells not explicitely mentioned as source cells for other
                # attributes
                range_cells_names = []
                in_range = False
                for col_name in cols_names:
                    col_is_not_range = not col_name or col_name in known_cols_names
                    if col_is_not_range:
                        if in_range:
                            break  # all range cells processed
                        continue  # skip first columns
                    in_range = True
                    range_cells_names.append(col_name)

                if not range_cells_names and not attr_rrules.column_is_optional:
                    raise ValueError(
                        f"no columns corresponding to ranged "
                        f"attribute '{attr_rrules.attr_name}'. List of all "
                        f"columns names: {cols_names}")

                range_cells_ids = [
                    col_names_ids[n] for n in range_cells_names]

                self.columns_map.append((range_cells_names, range_cells_ids))
            else:
                # this is 'usual' attribute, it's value is taken from s single cell
                col_id = col_names_ids.get(attr_rrules.column_name, None)
                if col_id is None and not attr_rrules.column_is_optional:
                    raise ValueError(
                        f"column {attr_rrules.column_name} required for "
                        f"attribute {attr_rrules.attr_name} is not found. "
                        f"List of all columns names: {cols_names}")
                self.columns_map.append(col_id)

    def cells_from_row(self, row):
        """Get cells and types in format expected by XlsObject.construct """
        assert self.columns_map is not None, (
            "_ObjScrCellsMap is not ready: call 'bind_titles_row' "
            "to finish init.")
        def _get_cells_for_attr(cols_ids):
            # get cells corresponding to a single attribute
            if isinstance(cols_ids, int):
                # 'simple' attribute
                return row[cols_ids]
            if cols_ids is None:
                # this attribute was explicetly ignored in reading rules
                return None
            # range attribute
            cols_names, cells_ids = cols_ids
            return cols_names, [row[i] for i in cells_ids]

        cells = [
            _get_cells_for_attr(cols_ids)
            for cols_ids in self.columns_map
        ]

        return self.cells_types, cells


class XlsTableReader:
    """Object which reads data from excel table.

    For each line of the table one or several objects are created (according to
    specified transformations rules).
    """
    def __init__(self, *objs_rrules, stop_on="blank all"):
        self.objs_rrules = objs_rrules  # [XlsObjReadRules, ]
        self.cells_maps = [
            _ObjScrCellsMap(obj_rrule.attrs_rules) for obj_rrule in self.objs_rrules]
        self.stop_on = stop_on

    def read_table(self, worksheet):
        """Generate tuples of XlsObjects according to self.objs_rrules."""
        titles_processed = False

        for row in worksheet.iter_rows():
            # skip optional first empty rows
            if not titles_processed and self._row_is_empty(row):
                continue

            # detect end of table
            if titles_processed:
                if self.stop_on == 'blank first':
                    if self._cell_is_empty(row[0]):
                        break
                else:
                    if self._row_is_empty(row):
                        break

            if not titles_processed:
                # this is a titles row. Time to prepare mappings
                cols_names = [cell.value for cell in row]
                col_names_ids = {
                    col_name: i for i, col_name in enumerate(cols_names)}
                known_cols_names = {
                    col_name
                    for cells_map in self.cells_maps
                    for col_name in cells_map.get_known_columns_names()}
                for cells_map in self.cells_maps:
                    cells_map.bind_titles_row(
                        cols_names, col_names_ids, known_cols_names)
                titles_processed = True
                continue

            # create result objects from current row
            results = []
            for obj_rrules, cells_map in zip(self.objs_rrules, self.cells_maps):
                cells_types, cells_list = cells_map.cells_from_row(row)
                results.append(
                    obj_rrules.obj_class.construct(cells_types, cells_list))

            yield results

    @classmethod
    def _row_is_empty(cls, row):
        return all(cls._cell_is_empty(cell) for cell in row)

    @classmethod
    def _cell_is_empty(cls, cell):
        return cell.value is None or str(cell.value).strip() == ""


def read_table(worksheet, xls_obj_class, attrs_rules, *, stop_on="blank all"):
    """This method should be used to read data from excel table in most cases.

    Arguments:
    - worksheet: excel worksheet (use openpyxl package to open excel file and
        get the worksheet object)
    - xls_obj_class: XlsObject-derived class, which desribes objects to be
        read from the table
    - attrs_rules: dictionary of rules of reading individual attrbutes of
        the result objects. Example:
        {
            'attr0_name': ("Column name", cell_type),
            'attr1_name': ("*", range_cell_type),
        }

    Method yields object of xls_obj_class.
    """
    obj_rrules = XlsObjReadRules(xls_obj_class, attrs_rules)

    table_reader = XlsTableReader(obj_rrules, stop_on=stop_on)

    for (x, ) in table_reader.read_table(worksheet):
        yield x


cell_str = CellStr()
cell_int = CellInt()
cell_bool = CellBool()
cell_list = CellList()
