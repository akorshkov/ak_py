"""Implementation of 'h' and 'll' methods to be used in python console.

'h' method is similar to standard python's 'help' method. Information it
produces is also based on doc strings, but it tends to provide less text and
is more sutable for fast lookup of available methods, signatures, etc.

'll' method is designed to print information about objects available in
python's concole scope.
"""

import inspect
from ak.color import ColorFmt, Palette


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

class HCommand:
    """Implementation of 'h' command.

    h(obj) prints some text related to the 'obj'. The text is produced by
    HDocItem object stored at obj._h_doc.
    """

    _DFLT_FILT_ARG = object()

    def __init__(self):
        self.palette = Palette({
            'func_name': ColorFmt("BLUE"),
            'tags':  ColorFmt("GREEN"),
            'warning': ColorFmt('RED'),
        })

    def __call__(self, obj, filt=_DFLT_FILT_ARG):
        # this method does not return the help text, but prints it
        # to make sure color sequences are printed properly.
        # (python interpreter does not display color sequences when
        # printing out object's repr)
        print(self._make_help_text(obj, filt))

    def _make_help_text(self, obj, filt=_DFLT_FILT_ARG):
        # prepare help text to be printed by __call__.
        # It's a separate method to be used in tests.
        return "\n".join(
            self._gen_help_text(obj, filt, fmt_all_dets=False, fmt_oneline=False)
        )

    def _gen_help_text(self, obj, filt, fmt_all_dets, fmt_oneline):
        # generate lines of text which make output of 'h' command

        # Object is h-doc capable if it has '_h_doc' attribute.
        if hasattr(obj, '_h_doc'):
            yield from obj._h_doc.gen_help_text(
                obj, filt, self.palette, fmt_all_dets, fmt_oneline)


class HDocItem:
    """Base for classes which hold h-doc information for some object"""

    def gen_help_text(self, obj, filt, palette, fmt_all_dets, fmt_oneline):
        """Generate h-doc text for an object.

        Arguments:
        - obj: the object to generate help for. It is supposed
            that self is obj._h_doc
        - filt: some object which can be specified to modify generated help text.
            Processing of this object may be implemented in derived classes.
        - palette: colors to be used
        - fmt_all_dets: specifies if to display "more details".
            Processing to be implemented in derived classes.
        - fmt_oneline: henerate one-line help.
        """
        assert hasattr(obj, '_h_doc')
        assert obj._h_doc is self

        if fmt_oneline:
            yield from self._gen_help_oneline(obj, filt, palette, fmt_all_dets)
        else:
            yield from self._gen_help_text(obj, filt, palette, fmt_all_dets)

    def _gen_help_text(self, _obj, _filt, _palette, _fmt_all_dets,
                       _bm_notes=None):
        # to be implemented in derived classes
        yield ""
        raise NotImplementedError

    def _gen_help_oneline(self, _obj, _filt, _palette, _fmt_all_dets,
                          _bm_notes=None):
        # to be implemented in derived classes
        yield ""
        raise NotImplementedError


class _BoundMethodNotes:
    # Additional information about a method in context of an object (bound
    # method)

    __slots__ = 'is_available', 'note_short', 'note_line'

    def __init__(self, is_available, note_short, note_line):
        """Create notes for method in context of object (bound method).

        Arguments:
        - is_available: False if it does not make sence to call the bound method
        - note_short:  text to be included into h-doc of the bound method.
                       F.e.: "n/a"
       - note_line:  text to be included into h-doc of the bound method. F.e.:
                     "! requires tocken access, not basic auth !"
        """
        self.is_available = is_available
        self.note_short = note_short
        self.note_line = note_line


class _ParsedDocStr:
    # Parse doc string which is expected to be in the following form:
    #
    # """Short description
    #
    # Detailed description which
    # can take several lines.
    #
    # #tag1 #tag2 #more_tags
    # """
    __slots__ = (
        'short_descr',  # first line of doc string
        'body_lines',  # body of doc string w/o first line and lines with tags
        'tags',  # list of all tags
    )

    def __init__(self, doc_string):
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
        self.tags = list(self._parse_tags(hashtag_lines))

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


class HDocItemFunc(HDocItem):
    """Data for h-doc of a function or a method of class."""
    __slots__ = (
        'name',
        'arg_names',  # [arg_name, ]
        'short_descr',  # first line of doc string
        'body_lines',  # body of doc string w/o first line and lines with tags
        'main_tag',  # the first tag (or 'misc' if no tags present)
        'tags',  # list of all tags
    )

    def __init__(self, func, func_name, doc_string):
        """HDocItemFunc - 'h' metadata about a single function/method.

        Arguments:
        - func: the function to generate the HelpItem for
        - func_name: name of this function
        - doc_string: doc string specified for this function.
        """
        self.name = func_name

        # inspect function signature
        f_signature = inspect.signature(func)
        self.arg_names = [
            str(inspected_arg)
            for name, inspected_arg in f_signature.parameters.items()
            if name != 'self']

        ds = _ParsedDocStr(doc_string)

        self.short_descr = ds.short_descr
        self.body_lines = ds.body_lines
        self.tags = ds.tags
        self.main_tag = self.tags[0] if self.tags else "misc"

    def _gen_help_oneline(self, obj, _filt, palette, _fmt_all_dets,
                          _bm_notes=None):
        # generate one-line function description

        bm_notes = _bm_notes or self._get_bound_method_notes(obj, palette)

        f_name = palette.get_color('func_name')(self.name)
        args_descr = ", ".join(self.arg_names)
        yield f"{f_name}({args_descr}) {bm_notes.note_short} {self.short_descr}"

    def _gen_help_text(self, obj, _filt, palette, _fmt_all_dets,
                       _bm_notes=None):
        # generate detailed function description

        bm_notes = _bm_notes or self._get_bound_method_notes(obj, palette)

        yield from self._gen_help_oneline(
            obj, _filt, palette, _fmt_all_dets, bm_notes)

        if bm_notes.note_line:
            yield f"    {bm_notes.note_line}"

        for line in self.body_lines:
            yield f"    {line}"

        def _gen_tags():
            yield self.main_tag
            for tag in self.tags:
                if tag != self.main_tag:
                    yield tag

        ct = palette.get_color('tags')
        tags = " ".join(f"#{ct(tag)}" for tag in _gen_tags())
        yield "    " + tags

    def _get_bound_method_notes(self, obj, palette) -> _BoundMethodNotes:
        # get the _BoundMethodNotes in case the h-doc is being generated
        # for bound method
        try:
            # detect situation when h-doc is generated for bound method.
            # In this case obj is obj_of_class.some_method, and we will
            # try to call obj_of_class._get_hdoc_method_notes
            notes_method = obj.__self__._get_hdoc_method_notes
        except AttributeError:
            return _BoundMethodNotes(True, "", "")

        return _BoundMethodNotes(*notes_method(self, palette))


class HDocItemCls(HDocItem):
    """Data for h-doc of class."""

    __slots__ = (
        'name',
        'h_items_by_name',
        'h_items_by_tag',  # {tag: [h_items having this main_tag]}
        'short_descr', # short description from doc_string
        'body_doc', # body of the doc string
    )

    def __init__(self, class_obj):
        self.name = class_obj.__name__

        ds = _ParsedDocStr(getattr(class_obj, '__doc__', ""))
        self.short_descr = ds.short_descr
        self.body_doc = ds.body_lines

        # collect method's h-items from base classes
        self.h_items_by_name = {}

        try:
            base_classes = class_obj.mro()
        except Exception:
            base_classes = []

        for bc in reversed(base_classes):
            try:
                base_h_items = bc._h_doc.h_items_by_name
            except AttributeError:
                base_h_items = {}

            for name, h_item in base_h_items.items():
                self.h_items_by_name[name] = h_item

        # process h-items of methods defined in current class
        for h_item in self._create_hitems_for_methods(class_obj):
            if 'no_hdoc' not in h_item.tags:
                self.h_items_by_name[h_item.name] = h_item

        self.h_items_by_tag = {}  # {main_tag: [h_item, ]}
        for h_item in self.h_items_by_name.values():
            self.h_items_by_tag.setdefault(h_item.main_tag, []).append(h_item)
        for h_items in self.h_items_by_tag.values():
            h_items.sort(key=lambda x: x.name)

    @staticmethod
    def _create_hitems_for_methods(class_obj):
        # create h_items for methods of class_obj

        assert hasattr(class_obj, '__dict__'), (
            "Expected some class. Arg is: " + str(
                type(class_obj)) + " " + str(class_obj)
        )

        # detect if base class already has h-docs (that must be inherited
        # from parent class)
        try:
            parent_class_h_items = class_obj._h_doc.h_items_by_tag
        except AttributeError:
            parent_class_h_items = {}

        h_items_by_name = {
            h_item.name: h_item
            for h_items in parent_class_h_items.values()
            for h_item in h_items
        }

        # process methods defined in current class
        for attr_name, attr_value in class_obj.__dict__.items():
            if hasattr(attr_value, '_h_doc'):
                # h-doc was already prepared (with explicit decorator)
                h_item = attr_value._h_doc
                if attr_name != h_item.name:
                    # this can happen if methods defined in class are renamed
                    # (f.e. by meta-class magic).
                    # In any case, help for this class should report
                    # this method with a name it can be accessed by, that is
                    # by current attr_name
                    h_item.name = attr_name
                h_items_by_name[h_item.name] = h_item
                continue
            if attr_name.startswith('__'):
                continue
            doc_str = getattr(attr_value, '__doc__', None)
            if doc_str and callable(attr_value):
                h_item = HDocItemFunc(attr_value, attr_name, doc_str)
                attr_value._h_doc = h_item
                h_items_by_name[h_item.name] = h_item

        for h_item in h_items_by_name.values():
            yield h_item

    def _gen_help_oneline(self, _obj, _filt, palette, _fmt_all_dets,
                          _bm_notes=None):
        # generate one-line class description
        assert _bm_notes is None, (
            "'_bm_notes' are applicable for bound methods, but this mehod "
            "generates h-doc for class or object of class")

        cls_name = palette.get_color('class_name')(self.name)

        yield f"{cls_name}  {self.short_descr}"

    def _gen_help_text(self, obj, _filt, palette, _fmt_all_dets,
                       _bm_notes=None):
        # generate detailed class (or object) description

        assert _bm_notes is None, (
            "'_bm_notes' are applicable for bound methods, but this mehod "
            "generates h-doc for class or object of class")

        yield from self._gen_help_oneline(obj, _filt, palette, _fmt_all_dets)

        # generate descriptions of methods
        for tag, h_items in self.h_items_by_tag.items():
            ct = palette.get_color('tags')
            yield f"#{ct(tag)}"
            for h_item in h_items:
                # in case we generate h-doc not for a class but for an
                # object of class, the methods are actually bound methods and
                # additional information (bm_notes) may be available.
                bm_notes = self._get_bound_method_notes(obj, h_item, palette)
                if not bm_notes.is_available:
                    continue

                for method_help_line in h_item._gen_help_oneline(
                    obj, _filt, palette, _fmt_all_dets, bm_notes):
                    yield "  " + method_help_line

    def _get_bound_method_notes(self, obj, h_item, palette):
        # get the _BoundMethodNotes for methods defined in the class if
        # h-doc is being generated not for a class, but for an object of
        # class.
        try:
            # check that obj._get_hdoc_method_notes is a bound method
            # (that would mean that 'obj' is not a class, but an object of
            # class, and _BoundMethodNotes may be available for other h-items)
            _ = obj._get_hdoc_method_notes.__self__
            is_obj = True
        except AttributeError:
            is_obj = False

        if is_obj:
            return _BoundMethodNotes(*obj._get_hdoc_method_notes(h_item, palette))

        return _BoundMethodNotes(True, "", "")


def h_doc(obj):
    """Decorator which creates h_doc data for a class or function.

    If is not necessary to use this decorator for each method of a class,
    it's enough to decorate class itself.
    """
    if isinstance(obj, type):
        obj._h_doc = HDocItemCls(obj)
    else:
        obj._h_doc = HDocItemFunc(obj, obj.__name__, obj.__doc__)

    return obj
