"""Implementation of 'h' and 'll' methods to be used in python console.

'h' method is similar to standard python's 'help' method. Information it
produces is also based on doc strings, but it tends to provide less text and
is more sutable for fast lookup of available methods, signatures, etc.

'll' method is designed to print information about objects available in
python's concole scope.
"""

import inspect
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
        # usually this method shoudl return tring. But python interpreter
        # does not print strings with color sequences properly. So, print it
        # and return nothing
        print("\n".join(line for line in self._make_ll_report()))

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


#########################
# 'h'-command specific classes

class HDocItemFunc:
    """Data for h-doc of function."""
    __slots__ = (
        'func_name',
        'arg_names',  # [arg_name, ]
        'short_descr',  # first line of doc string
        'body_lines',  # body of doc string w/o first line and lines with tags
        'main_tag',  # the first tag (or 'misc' if no tags present)
        'tags',  # set of all tags
    )

    def __init__(self, func, func_name, doc_string):
        """HDocItemFunc - 'h' metadata about a single function/method.

        Arguments:
        - func: the function to generate the HelpItem for
        - func_name: name of this function
        - doc_string: doc string specified for this function.
        """
        self.func_name = func_name

        # inspect function signature
        f_signature = inspect.signature(func)
        self.arg_names = [
            str(inspected_arg)
            for name, inspected_arg in f_signature.parameters.items()
            if name != 'self']

        # procede with doc string
        if doc_string is None:
            # doc string was not specified, but do not fail
            doc_string = ""
        lines = doc_string.split('\n')
        # remove first and last empty lines
        if lines and not lines[0].strip():
            lines.pop(0)
        if lines and not lines[-1].strip():
            lines.pop()

        # doc strings are aligned with corresponding functions
        # so usually each line starts with several space characters.
        # Remove these characters.
        n_spaces = [
            self._get_n_lead_spaces(line)
            for line in lines
        ]
        min_lead_spaces = min(
            (n for n in n_spaces if n),
            default = 0
        )
        if min_lead_spaces:
            lines = [
                line[min_lead_spaces:] if n_lead_spaces >= min_lead_spaces else line
                for line, n_lead_spaces in zip(lines, n_spaces)
            ]

        # short_descr and following blank line
        if lines:
            self.short_descr = lines.pop(0)
            if lines and not lines[0]:
                lines.pop(0)
        else:
            self.short_descr = "-??-"

        # last lines starting with '#' contain hashtags
        hashtag_lines = []
        while lines and lines[-1].startswith('#'):
            hashtag_lines.append(lines.pop())
        tags = list(self._parse_tags(hashtag_lines))

        self.main_tag = tags[0] if tags else 'misc'
        self.tags = set(tags)

        # body lines - all the remaining lines. Except trailing empty lines.
        while lines and not lines[-1]:
            lines.pop()
        self.body_lines = lines

    @staticmethod
    def _parse_tags(hashtag_lines):
        # docstring parser helper
        # ["#tag22", "#tag1 #tag2"] -> 'tag1', 'tag2', 'tag22'
        for line in reversed(hashtag_lines):
            for chunk in line.split():
                assert chunk.startswith('#'), (
                    f"hashtag should start with '#': {chunk}")
                yield chunk[1:]

    @staticmethod
    def _get_n_lead_spaces(line):
        # docstring parser helper
        # calculate number of leading spaces in string
        num_spaces = 0
        for ch in line:
            if ch == ' ':
                num_spaces += 1
            else:
                break
        return num_spaces

    def gen_lines_full(self, palette):
        """Generate lines of full help for object"""
        f_name = palette.color_fname(self.func_name)
        args_descr = ", ".join(self.arg_names)
        yield f"{f_name}({args_descr})  {self.short_descr}"

        for line in self.body_lines:
            yield f"    {line}"


class HDocItemCls:
    """Data for h-doc of class."""

    __slots__ = (
        'cls_name',
        'h_items_by_tag',  # {tag: [h_items having this main_tag]}
    )

    def __init__(self, class_obj):
        self.cls_name = class_obj.__name__

        self.h_items_by_tag = {}
        for h_item in self._create_hitems_for_methods(class_obj):
            self.h_items_by_tag.setdefault(h_item.main_tag, []).append(h_item)
        for h_items in self.h_items_by_tag.values():
            h_items.sort(key=lambda x: x.main_tag)

    @staticmethod
    def _create_hitems_for_methods(class_obj):
        # create h_items for methods of class_obj
        # returns set of all the h_items of class_obj which should be printed

        new_h_items = {}

        assert hasattr(class_obj, '__dict__'), (
            "Expected some class. Arg is: " + str(
                type(class_obj)) + " " + str(class_obj)
        )

        for attr_name, attr_value in class_obj.__dict__.items():
            if attr_name.startswith('__'):
                continue
            doc_str = getattr(attr_value, '__doc__', None)
            if doc_str:
                h_item = HDocItemFunc(attr_value, attr_name, doc_str)
                attr_value._h_doc = h_item
                if not getattr(attr_value, '_ignore_hdoc', False):
                    new_h_items[attr_name] = h_item

        # return all the help items
        # 1. first all the help_items of parent class
        if hasattr(class_obj, '_h_docs'):
            for h_item in class_obj._h_docs.h_items_by_tag.values():
                yield h_item

        # 2. and new help items (corresponding to methods in the class_obj)
        for h_item in new_h_items.values():
            yield h_item


def h_doc(obj):
    """Decorator which creates h_doc data for a class or function.

    If is not necessary to use this decorator for each method of a class,
    it's enough to decorate class itself.
    """
    if isinstance(obj, type):
        obj._h_docs = HDocItemCls(obj)
    else:
        obj._h_doc = HDocItemFunc(obj, obj.__name__, obj.__doc__)

    return obj


class HCommand:
    """Implementation of 'h' command."""

    def __init__(self):
        # self can be used as as palette for HDoc objects producing
        # colored help text. Colors available in palette:
        self.color_fname = ColorFmt("BLUE")
        self.color_tags = ColorFmt("GREEN")

    def __call__(self, obj):
        print("\n".join(self._gen_help_text(obj)))

    def _gen_help_text(self, obj):
        # generate lines of text which make output of 'h' command
        if hasattr(obj, '_h_doc'):
            yield from obj._h_doc.gen_lines_full(self)
