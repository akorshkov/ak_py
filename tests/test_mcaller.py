"""Test "methods wrapper" tools."""

import unittest

from ak.mcaller import method_attrs, MCaller
from ak.ppobj import PrettyPrinterBase


class _DummyPPrinter(PrettyPrinterBase):
    # dummy PrettyPrinter for tests - to be not default PrettyPrinter
    # is the only purpose of it
    def gen_pplines(self, _obj_to_print):
        """Generate lines of pretty text."""
        yield "dummy pprint string"


class TestMCallerClass(unittest.TestCase):
    """Test creation and basic properties of MCaller derived classes."""
    def test_simple_wrapper_class(self):

        dummy_pprinter = _DummyPPrinter()

        class MyMethodCaller(MCaller):
            def __init__(self, val):
                self.val = val

            @method_attrs(auth="x1x")
            def method_1(self, arg):
                """Test method.

                To check that it is properly decorated.
                """
                mtd_meta = self.get_mcaller_meta()
                return {
                    "arg": arg, "val": self.val,
                    "auth": mtd_meta.properties['auth']}

            @method_attrs(auth="x2x", pprint=dummy_pprinter)
            def method_2(self, arg):
                """Anothe test method.

                To check custom pretty-printing result.
                """
                mtd_meta = self.get_mcaller_meta()
                return {
                    "arg": arg, "val": self.val,
                    "auth": mtd_meta.properties['auth']}

            @method_attrs(auth="x3x")
            def method_3(self, arg):
                """Anothe test method.

                To check custom pretty-printing result.
                """
                mtd_meta = self.indirect_get_meta()
                _ = 42
                return {
                    "arg": arg, "val": self.val,
                    "auth": mtd_meta.properties['auth']}

            def _method_3_pprint(self, result_obj):
                """should provide custom pretty-printing for 'method_3'"""
                return "self repr string"

            def method_4(self, arg):
                """is not decorated, so should behave as usual method"""
                return {"arg": arg, "val": self.val}

            @method_attrs('componentA', pprint=None)
            def method_5(self, arg):
                """Method with pprint set to None explicitely.

                It will not return pprintable obj; '_r' version of the method
                will not be created.
                """
                return {"arg": arg, "val": self.val}

            @method_attrs(auth="x6x")
            def method_6(self, arg):
                """Method with custome _pprint, which is a generator."""
                return None

            def _method_6_pprint(self, result_obj):
                """should provide custom pretty-printing for 'method_6'"""
                yield "line1"
                yield "line2"

            def indirect_get_meta(self):
                """Test indirect calls of self.get_mcaller_meta.

                To test that inspect-related magic of self.get_mcaller_meta
                still works if it is called not directly from 'method_attrs'
                decorated method.
                """
                mtd_meta = self.get_mcaller_meta()
                return mtd_meta

        # 0. prepare an object for test
        tst_obj = MyMethodCaller(42)

        # 1. check behavior of method_1
        result = tst_obj.method_1(17)

        self.assertTrue(
            hasattr(result, 'r'),
            f"result of 'wrapped' method should be a pretty-printable object, "
            f"the original return value stored in result.r. Actual result is "
            f"{type(result)} : {str(result)}")

        raw_result = result.r

        self.assertEqual(raw_result['arg'], 17)
        self.assertEqual(raw_result['val'], 42)
        self.assertEqual(
            raw_result['auth'], "x1x",
            "this value is an argument of wrapper decorator and was stored "
            "in method's metadata")

        self.assertEqual(
            raw_result, tst_obj.method_1_r(17),
            "raw (not pprintable) result should be returned by '.._r' method")

        # 2. check behavior of method_2
        # This method has custom pprinter defined in the decorator
        result = tst_obj.method_2(18)

        raw_result = result.r
        self.assertEqual(raw_result['arg'], 18)
        self.assertEqual(raw_result['val'], 42)
        self.assertEqual(raw_result['auth'], "x2x")

        # make sure custom pprinter is used
        repr_str = result._get_repr_str()
        self.assertEqual(repr_str, "dummy pprint string")

        # 3. check behavior of method_3
        # This method uses pprinter method defind in the class
        # (_method_3_pprint)
        result = tst_obj.method_3(19)

        raw_result = result.r
        self.assertEqual(raw_result['arg'], 19)
        self.assertEqual(raw_result['val'], 42)
        self.assertEqual(raw_result['auth'], "x3x")

        # make sure custom pprinter is used
        repr_str = result._get_repr_str()
        self.assertEqual(repr_str, "self repr string")

        # 4. check get_mcaller_meta direct call
        try:
            tst_obj.get_mcaller_meta()
        except ValueError as err:
            msg = str(err)
            self.assertIn('get_mcaller_meta', msg)
        else:
            self.assertTrue(False, (
                "direct call of get_mcaller_meta must fail because "
                "the data it should return is not present in any "
                "method in the current call stack"))

        # 5. method with pprint=None
        self.assertTrue(hasattr(tst_obj, 'method_5'))
        self.assertFalse(hasattr(tst_obj, 'method_5_r'))

        result = tst_obj.method_5(17)
        self.assertTrue(
            isinstance(result, dict),
            "method is exected to return result as is, not pprintable object")

        self.assertEqual({'arg': 17, 'val': 42}, result)

        # 6. method with generator pprint
        result = tst_obj.method_6(17)

        repr_str = result._get_repr_str()
        self.assertEqual("line1\nline2", repr_str)
