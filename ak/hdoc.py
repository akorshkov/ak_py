"""Implementation of 'h' and 'll' methods to be used in python console.

'h' (and 'hh') methods print out a description of an object. It's a
responsibility of an object to provide the description. Object is
'h_doc friendly' if it has '_h_doc' attribute of HDocItem class.
Printed text should be similar to the doc string, main purpose is to
provide short fast lookup of available methods, their signatures, etc.
This module provides implemendations of 'h' (and 'hh') mehtods and tools
to make objects 'h_doc friendly'.

'll' method is designed to print information about objects available in
python's concole scope.
"""

import inspect
from typing import Iterator

from ak.color import SyntaxGroupsUser, SHText, sh_lines_fmt


#########################
# 'll'-command specific classes

class LLImpl(SyntaxGroupsUser):
    """Implementation of 'll' command.

    Usage:
    >>> ll = LLImpl(locals())
    >>> ll
    ... summary of local variables is printed ...
    """

    _SYNTAX_GROUPS_NAMES = {
        'NAME': 'NAME',
        'CATEGORY': 'CATEGORY',
    }

    def __init__(self, locals_dict):
        """Create 'll' object which prints summary of values in python console.

        Arguments:
        - locals_dict: dictionary of console's locals
        """
        self.locals_dict = locals_dict
        self.syntax_names = self.make_syntax_groups_names(None, None)

    def gen_sh_lines(self) -> Iterator[SHText]:
        # generate lines (SHText values) which make a summary of
        # variables in self.locals_dict

        # each category has list of items with description and list of
        # items w/o description
        items_by_category = {}  # {category_name: ([(name, descr), ], [name, ])}

        cat_sort_weights = {}

        for name, value in self.locals_dict.items():
            cat_sort_weight, category, descr = self._get_explicit_value_descr(value)
            assert category is not None

            # sorting rules of categories are not very strict. Guessed weight
            # may change from item to item, so update it after each item
            new_weight = min(cat_sort_weight,
                             cat_sort_weights.get(category, cat_sort_weight))
            cat_sort_weights[category] = new_weight

            if descr is not None:
                items_by_category.setdefault(
                    category, ([], []))[0].append((name, descr))
            else:
                if not name.startswith('_'):
                    items_by_category.setdefault(category, ([], []))[1].append(name)

        cat_is_first = True
        sorted_categories = sorted(
            items_by_category.keys(), key=lambda cat: (cat_sort_weights[cat], cat))
        for category_name in sorted_categories:
            if cat_is_first:
                cat_is_first = False
            else:
                yield SHText("")
            yield SHText((self.syntax_names['CATEGORY'], category_name), ":")
            items, items_wo_descr = items_by_category[category_name]
            if items:
                items.sort(key=lambda kv: kv[0])
                max_name_len = max(len(item[0]) for item in items)
                name_col_len = min(max_name_len, 20) + 1
                for name, descr in items:
                    c_name_descr = SHText(self.syntax_names['NAME'], name).fixed_len(
                        name_col_len)
                    c_name_descr += ("", f": {descr}")
                    yield c_name_descr
            if items_wo_descr:
                yield SHText("  ") + SHText(", ").join(
                    (self.syntax_names['NAME'], name)
                    for name in items_wo_descr)

    def _get_explicit_value_descr(self, value):
        # detect if data for 'll' report is present in the object and return it.
        #
        # information may be available either via value._get_ll_descr() or
        # value._get_ll_cls_descr(). There are two different methods because
        # it may be necessary to report some class and object of this class
        # with different descriptions.
        #
        # returns (cat_sort_weight, category, descr)
        # cat_sort_weight is used to organize categories in the printed report
        cat_sort_weight = 50
        category, descr = None, None
        if inspect.isclass(value):
            if hasattr(value, '_get_ll_cls_descr'):
                category, descr = value._get_ll_cls_descr()
                cat_sort_weight = 20
            else:
                category = value.__name__
                cat_sort_weight = 80
        else:
            if hasattr(value, '_get_ll_descr'):
                category, descr = value._get_ll_descr()
                cat_sort_weight = 20
            else:
                category = type(value).__name__
                cat_sort_weight = 80
        return cat_sort_weight, category, descr

    def _get_ll_descr(self):
        # ll-information about 'll' command itself
        return "Console tools", "Command which produced this summary"


#########################
# 'h'-command specific classes

class HCommand(SyntaxGroupsUser):
    """Implementation of 'h' command.

    h(obj) prints some text related to the 'obj'. The text is produced by
    HDocItem object stored at obj._h_doc.
    """

    _DFLT_FILT_ARG = object()
    _LEVEL_H, _LEVEL_HH = 1, 2  # correspond to 'h' and 'hh' commands

    _SYNTAX_GROUPS_NAMES = {
        'ATTR': 'ATTR',
        'FUNC_NAME': 'FUNC_NAME',
        'TAG': 'TAG',
        'WARN': 'WARN',
    }

    def __init__(self, dets_level=_LEVEL_H):
        self.syntax_names = self.make_syntax_groups_names(None, None)
        self.dets_level = dets_level

    def __call__(self, obj, filt=_DFLT_FILT_ARG):
        # this method does not return the help text, but prints it
        # to make sure color sequences are printed properly.
        # (python interpreter does not display color sequences when
        # printing out object's repr)
        print(self._make_help_text(obj, filt))

    def _make_help_text(self, obj, filt=_DFLT_FILT_ARG) -> str:
        # prepare help text to be printed by __call__.
        # It's a separate method to be used in tests.
        return "\n".join(
            str(colored_text)
            for colored_text in sh_lines_fmt(
                self._gen_sh_lines(
                    obj, filt, dets_level=self.dets_level, fmt_oneline=False))
        )

    def _gen_sh_lines(self, obj, filt, dets_level, fmt_oneline) -> Iterator[SHText]:
        # generate lines of text which make output of 'h' command

        # Object is h-doc capable if it has '_h_doc' attribute.
        if hasattr(obj, '_h_doc'):
            yield from obj._h_doc.gen_help_text(
                obj, filt, self.syntax_names, dets_level, fmt_oneline)

    def _get_ll_descr(self):
        # object description for 'll' command
        return "Console tools", "Help for misc classes and objects"


class HDocItem:
    """Base for classes which hold h-doc information for some object"""

    def gen_help_text(
        self, obj, filt, syntax_names, dets_level, fmt_oneline,
    ) -> Iterator[SHText]:
        """Generate h-doc syntax-highlihted text for an object.

        Arguments:
        - obj: the object to generate help for. It is supposed
            that self is obj._h_doc
        - filt: some object which can be specified to modify generated help text.
            Processing of this object may be implemented in derived classes.
        - syntax_names: syntax names to be used
        - dets_level: details level.
        - fmt_oneline: henerate one-line help.
        """
        assert hasattr(obj, '_h_doc')
        assert obj._h_doc is self

        if fmt_oneline:
            yield from self._gen_help_oneline(obj, filt, syntax_names, dets_level)
        else:
            yield from self._gen_help_text(obj, filt, syntax_names, dets_level)

    def _gen_help_text(
        self, _obj, _filt, _syntax_names, _dets_level, _bm_notes=None,
    ) -> Iterator[SHText]:
        # to be implemented in derived classes
        yield from[]
        raise NotImplementedError

    def _gen_help_oneline(
        self, _obj, _filt, _syntax_names, _dets_level, _bm_notes=None,
    ) -> Iterator[SHText]:
        # to be implemented in derived classes
        yield from []
        raise NotImplementedError


class BoundMethodNotes:
    """h_doc-related info about a bound method.

    In case the help is generated for a bound method (f.e. 'h(x.method)')
    the information is taken from two objects:
    1. x.method._h_doc - 'static' HDocItem object, which does not depend
      from the object 'x'
    2. the BoundMethodNotes, which contains information about the 'method'
      in context of the object 'x'

    In order for this functionality to work the 'x' object should have
    implemented a method '_get_hdoc_method_notes'. Like this:

    class ClassX:
        def _get_hdoc_method_notes(self, bound_method, syntax_names):
            assert self is bound_method.__self__
            assert hasattr(bound_method, '_h_doc')
            ...
            return BoundMethodNotes(...)
    """

    __slots__ = 'is_available', 'note_short', 'note_line'

    def __init__(self, is_available, note_short, note_line):
        """Create notes for method in context of object (bound method).

        Arguments:
        - is_available: False if it does not make sence to call the bound method
        - note_short:  SHText to be included into h-doc of the bound method.
                       F.e.: "n/a"
        - note_line:  SHtext to be included into h-doc of the bound method. F.e.:
                      "! requires token access, not basic auth !"
        """
        for arg, name in [(note_short, 'note_short'), (note_line, 'note_line')]:
            assert isinstance(arg, (str, SHText)), (
                f"'{name}' argument has unexpected type {type(arg)}. "
                f"Either SHText or str is expected")
        if isinstance(note_short, str):
            note_short = SHText(note_short)

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
        'hidden',  # do not include this method in class help text
        'arg_names',  # [arg_name, ]
        'short_descr',  # first line of doc string
        'body_lines',  # body of doc string w/o first line and lines with tags
        'main_tag',  # the first tag (or 'misc' if no tags present)
        'tags',  # list of all tags
    )

    _CHUNK_SPACE_HASHSYMBOL = SHText._Chunk("", " #")

    def __init__(self, func, func_name, doc_string, hidden=False):
        """HDocItemFunc - 'h' metadata about a single function/method.

        Arguments:
        - func: the function to generate the HelpItem for
        - func_name: name of this function
        - doc_string: doc string specified for this function.
        """
        self.name = func_name
        self.hidden = hidden

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

    def _gen_help_oneline(
        self, obj, _filt, syntax_names, _dets_level, _bm_notes=None,
    ) -> Iterator[SHText]:
        # generate one-line function description

        bm_notes = _bm_notes or self._get_bound_method_notes(obj, syntax_names)

        args_descr = ", ".join(self.arg_names)
        yield SHText(
            (syntax_names['FUNC_NAME'], self.name),
            ("", f"({args_descr}) "),
            bm_notes.note_short,
            f" {self.short_descr}",
        )

    def _gen_help_text(
        self, obj, _filt, syntax_names, _dets_level, _bm_notes=None,
    ) -> Iterator[SHText]:
        # generate detailed function description

        bm_notes = _bm_notes or self._get_bound_method_notes(obj, syntax_names)

        yield from self._gen_help_oneline(
            obj, _filt, syntax_names, _dets_level, bm_notes)

        if bm_notes.note_line:
            yield SHText("    ", bm_notes.note_line)

        for line in self.body_lines:
            yield SHText(f"    {line}")

        def _gen_tags():
            yield self.main_tag
            for tag in self.tags:
                if tag != self.main_tag:
                    yield tag

        ct = syntax_names['TAG']
        sh_text_chunks = [SHText._Chunk("", "   ")]
        for tag in _gen_tags():
            sh_text_chunks.append(self._CHUNK_SPACE_HASHSYMBOL)
            sh_text_chunks.append(SHText._Chunk(ct, tag))

        yield SHText.make(sh_text_chunks)

    def _get_bound_method_notes(self, obj, syntax_names) -> BoundMethodNotes:
        # get the BoundMethodNotes in case the h-doc is being generated
        # for bound method
        try:
            # detect situation when h-doc is generated for bound method.
            # In this case obj is obj_of_class.some_method, and we will
            # try to call obj_of_class._get_hdoc_method_notes
            notes_method = obj.__self__._get_hdoc_method_notes
        except AttributeError:
            return BoundMethodNotes(True, "", "")

        # if we got here the 'obj' corresponds to bound method
        return notes_method(obj, syntax_names)


class HDocItemCls(HDocItem):
    """Data for h-doc of class."""

    __slots__ = (
        'name',
        'hidden',  # reserved, used in HDocItemFunc only
        'h_items_by_name',
        'h_items_by_tag',  # {tag: [h_items having this main_tag]}
        'short_descr',  # short description from doc_string
        'body_doc',  # body of the doc string
    )

    def __init__(self, obj_class, explicit_only=False):
        """Create h-doc for a class.

        If 'explicit_only' is false, h-docs will be automatically
        generated for methods defind in the class.
        """
        self.name = obj_class.__name__
        self.hidden = False

        ds = _ParsedDocStr(getattr(obj_class, '__doc__', ""))
        self.short_descr = ds.short_descr
        self.body_doc = ds.body_lines

        # collect method's h-items from base classes
        self.h_items_by_name = {}

        try:
            base_classes = obj_class.mro()
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
        for h_item in self._generate_hitems_for_methods(obj_class, explicit_only):
            if 'no_hdoc' not in h_item.tags:
                self.h_items_by_name[h_item.name] = h_item

        self.h_items_by_tag = {}  # {main_tag: [h_item, ]}
        for h_item in self.h_items_by_name.values():
            self.h_items_by_tag.setdefault(h_item.main_tag, []).append(h_item)
        for h_items in self.h_items_by_tag.values():
            h_items.sort(key=lambda x: x.name)

    @staticmethod
    def _generate_hitems_for_methods(obj_class, explicit_only):
        # create h_items for methods of obj_class

        assert hasattr(obj_class, '__dict__'), (
            "Expected some class. Arg is: " + str(
                type(obj_class)) + " " + str(obj_class)
        )

        # detect if base class already has h-docs (that must be inherited
        # from parent class)
        try:
            parent_class_h_items = obj_class._h_doc.h_items_by_tag
        except AttributeError:
            parent_class_h_items = {}

        h_items_by_name = {
            h_item.name: h_item
            for h_items in parent_class_h_items.values()
            for h_item in h_items
        }

        # process methods defined in current class
        for attr_name, attr_value in obj_class.__dict__.items():
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
            if explicit_only:
                continue
            if attr_name.startswith('_'):
                continue
            doc_str = getattr(attr_value, '__doc__', None)
            if doc_str and callable(attr_value):
                h_item = HDocItemFunc(attr_value, attr_name, doc_str)
                attr_value._h_doc = h_item
                h_items_by_name[h_item.name] = h_item

        for h_item in h_items_by_name.values():
            yield h_item

    def _gen_help_oneline(
        self, obj, _filt, syntax_names, _dets_level, _bm_notes=None,
    ) -> Iterator[SHText]:
        # generate one-line class or object description
        assert _bm_notes is None, (
            "'_bm_notes' are applicable for bound methods, but this mehod "
            "generates h-doc for class or object of class")

        obj_indicator = "" if inspect.isclass(obj) else "Object of "

        yield SHText(f"{obj_indicator}{self.name}  {self.short_descr}")

    def _gen_help_text(
        self, obj, _filt, syntax_names, dets_level, _bm_notes=None,
    ) -> Iterator[SHText]:
        # generate detailed class (or object) description
        #
        # In case "h(x.method)" was called, of this method will be:
        # self - ClassOfX._h_doc
        # obj - x.method

        assert _bm_notes is None, (
            "'_bm_notes' are applicable for bound methods, but this mehod "
            "generates h-doc for class or object of class")

        yield from self._gen_help_oneline(obj, _filt, syntax_names, dets_level)

        # generate description of attributes
        if hasattr(obj, '_HDOC_ATTRS'):
            is_class = inspect.isclass(obj)
            attrs_hdocs = []  # [(attr_name, sh_descr), ]
            color_attr = syntax_names['ATTR']
            color_warning = syntax_names['WARN']
            for attr_name, attr_descr in obj._HDOC_ATTRS:
                include_attr = True
                attr_is_available = True
                if not is_class:
                    if getattr(obj, attr_name, None) is None:
                        include_attr = dets_level >= HCommand._LEVEL_HH
                        attr_is_available = False
                if include_attr:
                    if not attr_is_available:
                        attr_descr = SHText(
                            (color_warning, "<n/a>"),
                            " ",
                            attr_descr)
                    attrs_hdocs.append((attr_name, attr_descr))
            if attrs_hdocs:
                yield SHText("Attributes:")
                max_name_len = max(len(attr_name) for attr_name, _ in attrs_hdocs)
                max_name_len = max(max_name_len, 5)
                for attr_name, attr_descr in attrs_hdocs:
                    yield SHText(
                        "  ",
                        (color_attr, f"{attr_name:{max_name_len}}"),
                        " - ",
                        attr_descr)

        # check if report methods defined in class, but n/a in the obj.
        # F.e. the method requires some authorization not provided
        # by the obj - technically you can call the obj.method, but
        # will get an error.
        report_na_methods = dets_level >= HCommand._LEVEL_HH

        # generate descriptions of methods
        for tag, h_items in self.h_items_by_tag.items():
            ct = syntax_names['TAG']
            tag_line_reported = False
            for h_item in h_items:
                if h_item.hidden:
                    continue
                # in case we generate h-doc not for a class but for an
                # object of class, the methods are actually bound methods and
                # additional information (bm_notes) may be available.
                bm_notes = self._get_bound_method_notes(obj, h_item, syntax_names)
                if not bm_notes.is_available and not report_na_methods:
                    continue

                if not tag_line_reported:
                    yield SHText("#", (ct, tag))
                    tag_line_reported = True

                for method_help_line in h_item._gen_help_oneline(
                    obj, _filt, syntax_names, dets_level, bm_notes,
                ):
                    yield SHText("  ", method_help_line)

    def _get_bound_method_notes(self, obj, h_item, syntax_names) -> BoundMethodNotes:
        # get the BoundMethodNotes for methods defined in the class if
        # h-doc is being generated not for a class, but for an object of
        # class.
        #
        # If we got here the 'obj' may be either a class or an object
        try:
            # check that obj._get_hdoc_method_notes is a bound method
            # (that would mean that 'obj' is not a class, but an object of
            # class, and BoundMethodNotes may be available for other h-items)
            obj_self = obj._get_hdoc_method_notes.__self__
        except AttributeError:
            obj_self = None

        if obj_self:
            # if we get here the 'obj' is an object of class
            attr = getattr(obj, h_item.name, None)
            assert attr is not None, (
                f"Object '{obj}' of type '{type(obj)}' has no attr '{h_item.name}'"
            )

            if callable(attr) and hasattr(attr, '__self__'):
                # attr is bound method. BoundMethodNotes can be created for it.
                return obj_self._get_hdoc_method_notes(attr, syntax_names)

        return BoundMethodNotes(True, "", "")


def h_doc(obj=None, *, explicit_only=False, hidden=False):
    """Decorator which creates h_doc data for a class or function.

    If is not necessary to use this decorator for each method of a class,
    it's enough to decorate class itself.

    Arguments:
    - explicit_only: do not automatically create h-docs for methods defined in
    class. Applicable only when decorating classes.
    - hidden: mark h-doc generated for a method as 'hidden' - information about
    this method will not be included into help text generated for a class or
    object of class. Applicable only when decorating functions/methods.
    """
    if obj is not None:
        # decorator was used w/o parameters. The obj is actually an object
        # to be decorated
        dec = h_doc(explicit_only=explicit_only, hidden=hidden)
        return dec(obj)

    def decorator(xobj):
        if isinstance(xobj, type):
            assert hidden is False, (
                f"'hidden' parameter is not applicable for decorating "
                f"object of type {type(xobj)}.")
            xobj._h_doc = HDocItemCls(xobj, explicit_only)
        else:
            assert explicit_only is False, (
                f"'explicit_only' parameter is not applicable for decorating "
                f"object of type {type(xobj)}.")
            xobj._h_doc = HDocItemFunc(
                xobj, xobj.__name__, xobj.__doc__, hidden)

        return xobj

    return decorator
