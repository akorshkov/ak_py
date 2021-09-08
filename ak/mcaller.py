"""Tools for creation of "methods caller" objects.

"methods caller" object is basically a collection of python wrappers for
not-python methods (f.e. http rest methods).

F.e. you have an external system with REST api. To call these REST methods
you may want to create a python object, which keeps connection information,
and has 'wrapper' methods for the API. Tools in this module will help
to create such objects.

Main purpose is to make such methods to be easy to use from interactive
console:
- integrate such classes with ak.hdoc
- produce pretty-printed results
"""

from functools import wraps
import inspect
from ak.ppobj import PrettyPrinter
from ak.hdoc import h_doc


class Meta_MethodsCaller(type):
    """meta-class for "methods caller" classes.

    Decorates specified methods during creation of "methods caller" class.
    'Specified' (or 'wrapper') methods are methods having having '_mcaller_meta'
    attribute (contents of this attribute depends of method type and should
    be set by some decorator)

    As a result of this meta-processing each 'wrapper' method is replaced
    with a method with some new functionality:
    - self._mcaller_pre_call(_mcaller_meta) is called (this method can be
      implemented in your class)
    - makes method to return special object, whose repr pretty prints
      original result (*)
    - saves code of the original mehod as a new method (with '_r' suffix)

    '_mcaller_meta' objects are stored in _MCALLERS_METAS calss attribute,
    which is a dictionary {'original_method_name': the_mcaller_meta}.

    (*) by default pretty-printing is implemented by generic ak.ppobj.PrettyPrinter.
    You can override this behavior by one of the following ways:
    - specify a method '_{orig_method_name}_pprint' which should get result of
      the original method and yield lines of text
    - specify custom PrettyPrinter at _mcaller_meta['pprint'] or
      _mcaller_meta.pprint
    """

    def __new__(meta, classname, supers, classdict):
        new_methods = {}

        # '_MCALLERS_METAS' of this class will contain '_MCALLERS_METAS' from
        # parent classes, let's collect them
        assert '_MCALLERS_METAS' not in classdict, (
            f"Error processing '{classname}' calss:"
            f"'_MCALLERS_METAS' attribute should not be defined explicitely"
        )
        mcallers_metas = {
            orig_method_name: meta_obj
            for parent_class in reversed(supers)
            for orig_method_name, meta_obj in getattr(
                parent_class, '_MCALLERS_METAS', {})
        }

        for name, value in classdict.items():
            mcaller_meta = getattr(value, '_mcaller_meta', False)
            if not mcaller_meta:
                continue

            mcallers_metas[name] = mcaller_meta
            orig_method_body = value

            # result pretty printer may be:
            # 1. specified in the class
            obj_pprint_method_name = f"_{name}_pprint"
            # 2. specified in mcaller_meta object or default one
            pprinter_obj = _safe_get_attr(
                mcaller_meta, 'pprint', PrettyPrinter())

            decorated_method = meta._make_wrapped_caller_method(
                orig_method_body, mcaller_meta,
                obj_pprint_method_name, pprinter_obj)

            new_methods[name] = decorated_method

            raw_val_method_name = name + "_r"
            assert raw_val_method_name not in classdict, (
                f"Class '{classname}' has method '{name}' marked as 'wrapper' "
                f"(it has '_mcaller_meta' attribute), so '{raw_val_method_name}' "
                f"must not be explicitely declared")
            new_methods[raw_val_method_name] = orig_method_body

        classdict.update(new_methods)
        classdict['_MCALLERS_METAS'] = mcallers_metas

        # helper method to get method meta from inside the method
        # It will be included into the new class
        def _get_mcaller_meta(self):
            """Get _mcaller_meta from inside decorated method.

            Example of usage:
                @some_mcaller_decorator(properties)  # creates _mcaller_meta
                def call_some_api_method(self, arguments):
                    m = self._get_mcaller_meta()  # returns the _mcaller_meta
                                                  # created by decorator
            """
            if not hasattr(self, '_MCALLERS_METAS'):
                return None

            # in order to find out what method to get info for some
            # inspect-magic is required
            caller_code_obj = inspect.currentframe().f_back.f_code
            orig_method_name = caller_code_obj.co_name

            return self._MCALLERS_METAS.get(orig_method_name)

        classdict['_get_mcaller_meta'] = _get_mcaller_meta

        created_class = super().__new__(meta, classname, supers, classdict)

        # do not require to use @h_doc decorator explicitely
        created_class = h_doc(created_class)

        return created_class

    def _make_wrapped_caller_method(
            orig_method_body, mcaller_meta, obj_pprint_method_name, pprinter_obj):
        # create a decorated method, which will replace original method
        # in the created class.
        # One of the purposes of the decorated method is to return
        # pretty-printable object (to be displayed in python cosole)

        @wraps(orig_method_body)
        def decorated_method(self, *args, **kwargs):
            # pre-call hook
            if hasattr(self, '_mcaller_pre_call'):
                self._mcaller_pre_call(mcaller_meta)

            # actual method call
            result_obj = orig_method_body(self, *args, **kwargs)

            # decorate and return the result
            if hasattr(self, obj_pprint_method_name):
                pprinter = getattr(self, obj_pprint_method_name)
            else:
                pprinter = pprinter_obj

            return PPrintableResult(result_obj, pprinter)

        return decorated_method


class PPrintableResult:
    """Holds an object, repr() and pretty-prints the object.

    To be used by methods in python console.
    The original object is available as .r attribute.
    """

    __slots__ = 'r', '_pprinter'

    def __init__(self, result_obj, pprinter):
        self.r = result_obj
        self._pprinter = pprinter

    def __repr__(self):
        # method does not return the string, but prints it to preserve
        # colored formatting (python console sanitise result of repr before
        # printing it, so that colored strings are not printed properly)
        print(self._get_repr_str())
        return ""

    def __str__(self):
        return f"PPrintableResult {self.r}"

    def _get_repr_str(self):
        # is a separate method mostly for testing purposes
        return self._pprinter(self.r)


def _safe_get_attr(obj, attr_name, default=None):
    try:
        return getattr(obj, attr_name)
    except AttributeError:
        pass

    try:
        return obj[attr_name]
    except Exception:
        pass

    return default


def m_wrapper(**kwargs):
    """Simple decorator to mark method a 'wrapper'"""
    def decorator(method):
        method._mcaller_meta = kwargs.copy()
        return method

    return decorator
