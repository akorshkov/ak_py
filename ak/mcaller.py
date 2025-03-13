"""Tools for creation of "methods caller" objects.

"methods caller" object is basically a collection of python wrappers for
not-python methods (f.e. http rest methods).

F.e. you have an external system with REST api. To call these REST methods
you may want to create a python object, which keeps connection information,
and has 'wrapper' methods for the API. Tools in this module will help
to create such objects.

Main purpose is to make such methods to be easy to use from interactive
console.

"methods caller" classes are integrated with ak.hdoc
"""

import inspect
import logging
from functools import wraps
from ak.color import CHText
from ak.ppobj import PPWrap
from ak.hdoc import h_doc, BoundMethodNotes


logger = logging.getLogger(__name__)


class _Meta_MethodsCaller(type):
    """meta-class for "methods caller" classes.

    Decorates specified methods during creation of "methods caller" class.
    'Specified' (or 'wrapper') methods are methods having having '_mcaller_meta'
    attribute (contents of this attribute depends of method type and should
    be set by some decorator)
    """

    def __new__(meta, classname, supers, classdict):
        new_methods = {}

        # '_MCALLERS_METAS' of this class will include '_MCALLERS_METAS' from
        # parent classes, let's collect them
        assert '_MCALLERS_METAS' not in classdict, (
            f"Error processing '{classname}' calss:"
            f"'_MCALLERS_METAS' attribute should not be defined explicitely"
        )
        mcallers_metas = {
            orig_method_name: meta_obj
            for parent_class in reversed(supers)
            for orig_method_name, meta_obj in getattr(
                parent_class, '_MCALLERS_METAS', {}).items()
        }

        for name, value in classdict.items():
            mcaller_meta = getattr(value, '_mcaller_meta', False)
            if not mcaller_meta:
                continue

            mcallers_metas[name] = mcaller_meta
            orig_method_body = value
            decorated_method_body = meta._decorate_mcaller_method(
                name, orig_method_body)
            new_methods[name] = h_doc(decorated_method_body)

        classdict.update(new_methods)
        classdict['_MCALLERS_METAS'] = mcallers_metas

        # helper method to get method meta from inside the method
        # It will be included into the new class
        def get_mcaller_meta(self):
            """Get _mcaller_meta from inside decorated method.

            Example of usage:
                @some_mcaller_decorator(properties)  # creates _mcaller_meta
                def call_some_api_method(self, arguments):
                    m = self.get_mcaller_meta()  # returns the _mcaller_meta
                                                  # created by decorator
            """
            if not hasattr(self, '_MCALLERS_METAS'):
                return None

            # in order to find out what method to get info for some
            # inspect-magic is required
            cur_frame = inspect.currentframe().f_back
            while cur_frame is not None:
                cur_frame_name = cur_frame.f_code.co_name
                if cur_frame_name in self._MCALLERS_METAS:
                    return self._MCALLERS_METAS[cur_frame_name]
                cur_frame = cur_frame.f_back

            # metadata was not found. This means that there is no 'wrapper'
            # mehod in the current call stack. There is no _mcaller_meta
            # to return.
            raise ValueError(
                "No 'methods caller' metadata found. 'get_mcaller_meta' "
                "should be called from inside 'method wrapper' methods only."
            )

        classdict['get_mcaller_meta'] = get_mcaller_meta

        created_class = super().__new__(meta, classname, supers, classdict)

        # do not require to use @h_doc decorator explicitely
        created_class = h_doc(created_class, explicit_only=True)

        return created_class

    @classmethod
    def _decorate_mcaller_method(cls, method_name, orig_method_body):
        # mcaller methods automatically log calls. Implement this

        @wraps(orig_method_body)
        def decorated_method_body(*args, **kwargs):
            logger.info(f"++ {method_name}()")
            result = orig_method_body(*args, **kwargs)
            logger.info(f"-- {method_name}()")
            return result

        return decorated_method_body


# !!!! rename! 
class PPMethod(PPWrap):
    """Pretty-printable object with custom pprint method.

    The _pprint method may be either a usual method or generator,
    which generates lines of pretty text.
    """
    def __init__(self, obj_to_print, pp_method):
        self.r = obj_to_print
        self.pp_method = pp_method

    def __str__(self):
        if inspect.isgeneratorfunction(self.pp_method):
            return str(
                CHText("\n").join(self.pp_method(self.r)))
        else:
            return str(self.pp_method(self.r))


class MCallerMetaGeneral:
    """Properties of MethodCaller method.

    Created by 'method_attrs' decorator. Check this decorator for more details.
    """

    # name of the method, which will prepare BoundMethodNotes for
    # methods decorated with this decorator
    _MAKE_BM_NOTES_METHOD = '_make_bm_notes_general'

    __slots__ = 'pprinter', 'components', 'properties'

    def __init__(self, components, properties):
        self.components = components
        self.properties = properties


def method_attrs(*components, **kwargs):
    """Decorator to specify metadata for managed methods of MCaller.

    This decorator is quite generic: it allowes you to specify list of
    'components' required by a method, and a dictionary of any other
    attributes.

    List of required components will be used to check bound method availability.

    'pprint' is a special kwarg: if it is specified, it should be a custom
    pretty-printer, which will be used to print the results of the decorated
    method.
    """
    def decorator(method):
        method._mcaller_meta = MCallerMetaGeneral(components, kwargs)
        return method

    return decorator


class MCaller(metaclass=_Meta_MethodsCaller):
    """Base class for "method caller's".

    Main purpose is to make such objects of these classes console friendly.
    Methods, tuned to be called from python interactive console (console
    methods) produce pretty-printable results, objects are integrated with
    ak.hdoc help system ('h' command).

    If the 'console' mathod is a simple wrapper of an http call, inmlement
    this method in a class (mixin) derived from ak.mcaller_http.MCallerHttp,
    and then derive you class from that mixin. MCallerHttp implements
    implements functionality, which makes creation of http wrappers easier.
    Other such classes exist for wrappers of other types.
    """

    def _get_hdoc_method_notes(self, bound_method, _c) -> BoundMethodNotes:
        # generic implementation of the method wich returns BoundMethodNotes
        #
        # The result BoundMethodNotes depends on the type of the method.
        # Here try to find out type of the method, find corresponding method
        # which would create BoundMethodNotes, and call this corresponding
        # method.
        assert self is bound_method.__self__
        assert hasattr(bound_method, '_h_doc')

        if not hasattr(bound_method, '_mcaller_meta'):
            # looks like it's a 'usual' method
            # metatata not available - return default BoundMethodNotes
            return BoundMethodNotes(True, "", None)

        method_meta = bound_method._mcaller_meta

        # creation rules of BoundMethodNotes depend of method type.
        notes_maker_method_name = getattr(method_meta, '_MAKE_BM_NOTES_METHOD', "")
        notes_maker_method = getattr(self, notes_maker_method_name, None)

        if notes_maker_method is None:
            return BoundMethodNotes(True, "", "")

        return notes_maker_method(bound_method, _c)

    def _make_bm_notes_general(self, bound_method, _c) -> BoundMethodNotes:
        # create BoundMethodNotes for 'general' bound methods (methods
        # decorated with 'method_attrs' decorator)
        assert hasattr(bound_method, '_mcaller_meta')
        method_meta = bound_method._mcaller_meta
        assert hasattr(method_meta, 'components')

        available_components = getattr(self, 'available_components', [])
        missing_components = [
            n for n in method_meta.components if n not in available_components]

        if missing_components:
            return BoundMethodNotes(
                False,
                SHText(("WARN", "<n/a>")),  # !!!!  why SHText here and why no test?
                f"object has no access to components {missing_components}")
        else:
            return BoundMethodNotes(True, "", "")
