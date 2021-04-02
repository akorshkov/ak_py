"""Test hdoc module."""

import unittest

from ak.hdoc import HDocItemFunc, HDocItemCls, h_doc


class TestHDocItemFunc(unittest.TestCase):
    """Test h-doc created for a single function/method"""

    def test_usual_method(self):
        """Test creation of h-doc from proper doc string."""

        def some_method(param1, param2, param3, *args, **kwargs):
            """HDocItemFunc will be jenerated from this docstring.

            Detailed description of the
            method and what it does.

            More detail here.

            #tag1 #tag2 #tag3  #tag4
            """
            _ = param1, param2, param3, args, kwargs

        h_doc = HDocItemFunc(some_method, "some_method", some_method.__doc__)

        self.assertEqual("some_method", h_doc.func_name)
        self.assertEqual(
            "HDocItemFunc will be jenerated from this docstring.", h_doc.short_descr)
        self.assertEqual(
            ["param1", "param2", "param3", "*args",  "**kwargs"],
            h_doc.arg_names)
        self.assertEqual(
            [
                "Detailed description of the",
                "method and what it does.",
                "",
                "More detail here.",
            ],
            h_doc.body_lines)
        self.assertEqual("tag1", h_doc.main_tag)
        self.assertEqual({"tag1", "tag2", "tag3", "tag4"}, h_doc.tags)


class TestHDocItemCls(unittest.TestCase):
    """Test h-doc created for a class"""

    def test_success(self):
        """Test success scenario of h-doc creation for class."""

        class TClass:
            """HDocItemCls will be created from it."""

            def __init__(self, x):
                self.x = x

            def method_1(self):
                """will have h-doc

                Some description

                #tag_main #tag_1
                """
                return self.x

            def method_2(self):
                """will have no h-doc because explicitely turned off

                Some description

                #tag_main #tag_1
                """
                return self.x

            def method_2(self):
                # no doc string - no h-doc
                return self.x

        hdoc = HDocItemCls(TClass)
        self.assertEqual('TClass', hdoc.cls_name)
        self.assertIn('tag_main', hdoc.h_items_by_tag)
        self.assertNotIn('tag_1', hdoc.h_items_by_tag)

        self.assertEqual(1, len(hdoc.h_items_by_tag['tag_main']))


class TestHDocDecorator(unittest.TestCase):
    """Test behavior of h_doc decorator."""

    def test_h_doc_decorator_functions(self):
        """Test h_doc decorator with functions."""

        @h_doc
        def t1(a1):
            """some doc string"""
            _ = a1

        self.assertTrue(hasattr(t1, '_h_doc'))
        self.assertTrue(isinstance(t1._h_doc, HDocItemFunc))

        @h_doc
        def t2(a1):
            # no docstring here
            _ = a1

        self.assertTrue(hasattr(t2, '_h_doc'))
        self.assertTrue(isinstance(t2._h_doc, HDocItemFunc))

    def test_h_doc_decorator_class(self):
        """Test h_doc decorator with class."""

        @h_doc
        class TClass:
            """HDocItemCls will be created from it."""

            def __init__(self, x):
                self.x = x

            def method_1(self):
                """will have h-doc

                Some description

                #tag_main #tag_1
                """
                return self.x

        self.assertTrue(hasattr(TClass, '_h_docs'))
        h_docs = TClass._h_docs
        self.assertEqual(1, len(TClass._h_docs.h_items_by_tag['tag_main']))
