"""Mock of openpyxl package."""


class MockedWorkBook:
    """Mock of openpyxl Workbook."""

    def __init__(self, worksheets_data):
        self.worksheets = {
            sheet_name: MockedWorksheet(sheet_name, sheet_data)
            for sheet_name, sheet_data in worksheets_data}

    def __getitem__(self, ws_name):
        """Get worksheet by name."""
        assert isinstance(ws_name, str), (
            f"worksheet name must be a string. "
            f"Provided value '{ws_name}' is {str(type(ws_name))}.")
        try:
            return self.worksheets[ws_name]
        except KeyError:
            pass
        raise ValueError(
            f"worksheet '{ws_name}' not found. "
            f"Existing worksheets: {sorted(self.worksheets.keys())}")


class MockedWorksheet:
    """Mock of openpyxl Worksheet."""

    def __init__(self, name, lines):
        self.title = name

        self.xl_lines = []

        llen = None
        borders = None
        for line_n, line in enumerate(lines):
            if llen is None:
                # this is the first line, detect format
                llen = len(line)
                borders = [pos for pos, char in enumerate(line) if char == '|']
                assert borders[0] == 0
                assert borders[-1] == llen - 1

            assert len(line) == llen
            prev_b = None
            values = []
            for b in borders:
                assert line[b] == '|'
                if prev_b is not None:
                    col_n = len(values)
                    values.append(
                        Cell.make_cell(self, line_n, col_n, line[prev_b+1:b]))
                prev_b = b
            self.xl_lines.append(values)

    def __str__(self):
        return f'<Worksheet "{self.title}">'

    def __repr__(self):
        return str(self)

    def iter_rows(self):
        """Generate rows of cells in the worksheet."""
        for row in self.xl_lines:
            yield row


class Cell:
    """Mock of openpyxl Cell."""
    __slots__ = 'parent', 'coordinate', 'value'

    def __init__(self, ws, coordinate, value):
        self.parent = ws
        self.coordinate = coordinate  # example "B10"
        self.value = value

    def __str__(self):
        return f"<Cell '{self.parent.title}'.{self.coordinate}>"

    def __repr__(self):
        return str(self)

    @classmethod
    def make_cell(cls, parent, line, col, str_val):
        """Create Cell based on contents of the text table."""
        val = cls.cell_str_to_val(str_val)
        coordinate = cls.make_coordinate(line, col)
        return cls(parent, coordinate, val)

    @classmethod
    def cell_str_to_val(cls, str_value):
        """Contents of text table -> value for corresponding excel cell."""
        s = str_value.strip()
        if s == "":
            val = None
        elif s[0] == s[-1] and s[0] in ('"', "'"):
            val = s[1:-1]
        else:
            try:
                val = int(s)
            except ValueError:
                val = s
        return val

    @classmethod
    def col_name_to_index(cls, col_name):
        """Excel column names -> integer. 'A' -> 0, 'Z' -> 25, 'AA' -> 26"""
        col_index = 0
        for c in col_name:
            i = ord(c)
            if i < 65 or i > 90:
                raise ValueError(
                    f"Invalid column name '{col_name}': invalid char '{c}'. "
                    f"Valid characters are A-Z only.")
            col_index += 1
            col_index *= 26
            col_index += i - 65
        return col_index

    @classmethod
    def col_index_to_name(cls, col_index):
        """Column index -> excel column name. 0 -> 'A', 25 -> 'Z', 26 -> 'AA'"""
        assert col_index >= 0
        chars = []
        while True:
            i = col_index % 26
            chars.append(chr(65 + i))
            col_index -= i
            if col_index == 0:
                break
            col_index = col_index // 26
            col_index -= 1

        chars.reverse()
        return "".join(c for c in chars)

    @classmethod
    def make_coordinate(cls, line, col):
        """(0, 0) -> "A1", (0, 1) -> "B1", (10, 1) -> "B11", etc."""
        assert line >= 0
        assert col >= 0
        col_name = cls.col_index_to_name(col)
        return f"{col_name}{line+1}"
