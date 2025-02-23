"""Test "methods wrapper" tools."""

import unittest

from ak.mcaller import method_attrs, MCaller, PPMethod
from ak.ppobj import PPWrap


class TestMCallerClass(unittest.TestCase):
    """Test creation and basic properties of MCaller derived classes."""
    def test_simple_wrapper_class(self):

        class MyMethodCaller(MCaller):
            def __init__(self, val):
                self.val = val

            @method_attrs(auth="x1x")
            def method_1(self, arg):
                """Test method.

                To check that it is properly decorated.
                """
                mtd_meta = self.get_mcaller_meta()
                return PPWrap({
                    "arg": arg, "val": self.val,
                    "auth": mtd_meta.properties['auth']})

            @method_attrs(auth="x3x")
            def method_3(self, arg):
                """Another test method.

                To check custom pretty-printing result.
                """
                mtd_meta = self.indirect_get_meta()
                _ = 42
                return PPMethod({
                    "arg": arg, "val": self.val,
                    "auth": mtd_meta.properties['auth']
                }, self._method_3_pprint)

            def _method_3_pprint(self, result_obj):
                """should provide custom pretty-printing for 'method_3'"""
                return "self repr string"

            def method_4(self, arg):
                """is not decorated, so should behave as usual method"""
                return {"arg": arg, "val": self.val}

            @method_attrs(auth="x6x")
            def method_6(self, arg):
                """Method with custom _pprint, which is a generator."""
                return PPMethod(None, self._method_6_pprint)

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

        s = f"{result}"

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
            raw_result, tst_obj.method_1(17).r,
            "raw (not pprintable) result should be available in .r attr.")

        # 3. check behavior of method_3
        # This method uses pprinter method defind in the class
        # (_method_3_pprint)
        result = tst_obj.method_3(19)

        raw_result = result.r
        self.assertEqual(raw_result['arg'], 19)
        self.assertEqual(raw_result['val'], 42)
        self.assertEqual(raw_result['auth'], "x3x")

        # make sure custom pprinter is used
        repr_str = str(result.ch_text())
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

        # 6. method with generator pprint
        result = tst_obj.method_6(17)

        # repr_str = result.get_pptext() !!!
        repr_str = str(result)
        self.assertEqual("line1\nline2", repr_str)
