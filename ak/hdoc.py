"""Implementation of 'h' and 'll' methods to be used in python console.

'h' method is similar to standard python's 'help' method. Information it
produces is also based on doc strings, but it tends to provide less text and
is more sutable for fast lookup of available methods, signatures, etc.

'll' method is designed to print information about objects available in
python's concole scope.
"""

from ak.color import ColorFmt


#########################
# 'll'-command specific classes

class _LLImpl:
    """Implementation of 'll' command.

    Usage:
    >>> ll = _LLImpl(locals())
    >>> ll
    ... summary of local variables is printed ...
    """

    _COLOR_NAME = ColorFmt('GREEN', bold=True)
    _COLOR_CATEGORY = ColorFmt('MAGENTA', bold=True)

    def __init__(
            self, locals_dict, *,
            color_name=_COLOR_NAME,
            color_category=_COLOR_CATEGORY,
            use_colors=True):
        """Create 'll' object which prints summary of values in python console.

        Arguments:
        - locals_dict: dictionary of console's locals
        - color_name: specifies how names of variables are formatted
        - color_category: specifies how names of categories are formatted
        - use_colors: if False, the "color_*" arguments are ignored and
            plain text is produced.

        Note: You can specify 'color_*' arguments to override predefined
            colors. Check help(ColorFmt.make) for possible values of these
            arguments.
        """
        self.locals_dict = locals_dict
        self._color_name = ColorFmt.make(color_name, use_colors)
        self._color_category = ColorFmt.make(color_category, use_colors)

    def __repr__(self):
        return "\n".join(line for line in self._make_ll_report())

    def _make_ll_report(self):
        # generate lines (string values) which make a summary of
        # variables in self.locals_dict

        items_by_category = {}  # {category_name, [(name, descr), ]}
        misc_items = []  # [name, ]

        for name, value in self.locals_dict.items():
            category, descr = self._get_explicit_value_descr(value)
            if descr is not None and category is not None:
                items_by_category.setdefault(category, []).append((name, descr))
            else:
                if not name.startswith('_'):
                    misc_items.append(name)

        cat_is_first = True
        for category_name in sorted(items_by_category.keys()):
            if cat_is_first:
                cat_is_first = False
            else:
                yield ""
            yield str(self._color_category(category_name)) + ":"
            items = items_by_category[category_name]
            items.sort(key=lambda kv: kv[0])
            max_name_len = max(len(item[0]) for item in items)
            name_col_len = min(max_name_len, 20) + 1
            for name, descr in items:
                c_name = self._color_name(name)
                yield f"  {c_name:{name_col_len}}: {descr}"

        if misc_items:
            if not cat_is_first:
                yield ""
            yield str(self._color_category("Misc")) + ":"
            misc_items.sort()
            yield "  " + ", ".join(
                str(self._color_name(name)) for name in misc_items)

    def _get_explicit_value_descr(self, value):
        # detect if data for 'll' report is present in the object and return it.
        #
        # information may be available either via value._get_ll_descr() or
        # value._get_ll_cls_descr(). There are two different methods because
        # it may be necessary to report some class and object of this class
        # with different descriptions.
        category, descr = None, None
        if hasattr(value, '_get_ll_descr'):
            try:
                category, descr = value._get_ll_descr()
                return category, descr
            except:
                pass
        if hasattr(value, '_get_ll_cls_descr'):
            try:
                category, descr = value._get_ll_cls_descr()
                return category, descr
            except:
                pass

        return None, None

    def _get_ll_descr(self):
        return "Console tools", "Command which produced this summary"
