"""Test hdoc module."""

import unittest
from collections import namedtuple

from ak.color import CHText
from ak.hdoc import HCommand, HDocItemFunc, BoundMethodNotes, h_doc


class TestHDocItemFunc(unittest.TestCase):
    """Test h-doc created for a single function/method"""

    def test_usual_method(self):
        """Test creation of h-doc from proper doc string."""

        @h_doc
        def some_method(param1, param2, param3, *args, **kwargs):
            """HDocItemFunc will be jenerated from this docstring.

            Detailed description of the
            method and what it does.

            More detail here.

            #tag1 #tag2 #tag3  #tag4
            """
            _ = param1, param2, param3, args, kwargs

        # 1. make sure help text is generated correctly
        h = HCommand()._make_help_text

        help_text = h(some_method)

        self.assertTrue(help_text is not None)

        self.assertIn(
            'some_method', help_text,
            "default h_doc implementation for function should print "
            "function name")

        for arg_name in ['param1', 'param2', 'param3', 'args', 'kwargs']:
            self.assertIn(arg_name, help_text)

        for tag in ['tag1', 'tag2', 'tag3', 'tag4']:
            self.assertIn(tag, help_text)

        # 2. make some tests of h_doc internals
        h_doc_obj = HDocItemFunc(some_method, "some_method", some_method.__doc__)

        self.assertEqual("some_method", h_doc_obj.name)
        self.assertEqual(
            "HDocItemFunc will be jenerated from this docstring.",
            h_doc_obj.short_descr)

        self.assertEqual(
            ["param1", "param2", "param3", "*args",  "**kwargs"],
            h_doc_obj.arg_names)

        self.assertEqual(
            [
                "Detailed description of the",
                "method and what it does.",
                "",
                "More detail here.",
            ],
            h_doc_obj.body_lines)

        self.assertEqual("tag1", h_doc_obj.main_tag)
        self.assertEqual(["tag1", "tag2", "tag3", "tag4"], h_doc_obj.tags)


class TestHDocItemCls(unittest.TestCase):
    """Test h-doc created for a class"""

    def test_success(self):
        """Test success scenario of h-doc creation for class."""

        # 0. Prepare h-doc-capable classes (TClass and TDerived)
        @h_doc
        class TClass:
            """base class summary"""

            # such class attributes should not break hdocs
            SOME_CLASS_ATTR = {1:1, 2:2}
            SOME_TYPE = namedtuple('user', ['id', 'bloodtype'])

            def __init__(self, x):
                self.x = x

            def method_1(self, some_arg):
                """will have h-doc

                Some method_1 description

                #tag_main #tag_1
                """
                _ = some_arg
                return self.x

            def method_2(self):
                # no doc string - no h-doc
                return self.x

            @h_doc
            def method_3(self, some_arg):
                """Method with explicitely generated h_doc.

                Some more method_3 detail, but no tags at all.
                """
                return self.x, some_arg

        @h_doc
        class TDerived(TClass):
            """Derived class summary.

            More details of derived class.
            """
            def method_1(self, some_arg, other_arg):
                """Overridden method_1. No detailed descr.

                #tag_overridden_main #tag_1
                """
                return self.x, some_arg, other_arg

        # for tests prepare version of 'h' which does not print but return
        # help text
        h = HCommand()._make_help_text

        # 1. analyze h-doc generated for base class
        help_text = h(TClass)

        self.assertIn("TClass", help_text, "class name must be present")
        self.assertIn("base class summary", help_text,
                      "short descr must be present")
        self.assertIn("method_1", help_text)
        self.assertNotIn("method_2", help_text)
        self.assertIn("method_3", help_text)

        self.assertIn(
            'tag_main', help_text, "it's main tag of reported method_1")
        self.assertNotIn(
            'tag_1', help_text, "it is not a main tag of any reported method")

        # 1.1 analyze h-doc generated for object of base class
        base_obj = TClass(42)
        obj_help_text = h(base_obj)
        expected_text = "Object of " + help_text

        self.assertEqual(
            expected_text, obj_help_text,
            "default implementation of h-doc does not use information "
            "from object, only from class. So help generated for object "
            "is same as help generated for class (with indication that "
            "this is actually an object)")

        # 2. analyze h-doc for derived class
        help_text = h(TDerived)

        self.assertIn('TDerived', help_text, "class name must be present")
        self.assertIn("Derived class summary", help_text,
                      "short descr must be present")
        self.assertIn('method_1', help_text)
        self.assertNotIn('method_2', help_text)
        self.assertIn('method_3', help_text)

        self.assertIn(
            'tag_overridden_main', help_text,
            "it's main tag of reported method_1")
        self.assertNotIn(
            'tag_main', help_text,
            "method_1 is overridden, 'tag_main' is not a "
            "main tag of any reported method any more")
        self.assertNotIn(
            'tag_1', help_text, "it is not a main tag of any reported method")

        # 2.1 analyze h-doc generated for object of derived class
        derived_obj = TDerived(42)
        obj_help_text = h(derived_obj)

        self.assertEqual("Object of " + help_text, obj_help_text)

        # 3. analyze hdocs of methods in base class
        help_text = h(TClass.method_1)
        self.assertIn('method_1', help_text)
        self.assertNotIn('Overridden method_1', help_text)
        self.assertIn("will have h-doc", help_text)
        self.assertIn("Some method_1 description", help_text)
        self.assertIn("tag_main", help_text)
        self.assertNotIn("tag_overridden_main", help_text)
        self.assertIn("tag_1", help_text)

        # 4. analyze hdocs of methods in derived class
        help_text = h(TDerived.method_1)

        self.assertIn('method_1', help_text)
        # make sure help for overridden method is generated
        self.assertIn('Overridden method_1', help_text)
        self.assertNotIn("will have h-doc", help_text)
        self.assertNotIn("Some method_1 description", help_text)
        self.assertNotIn("tag_main", help_text)
        self.assertIn("tag_overridden_main", help_text)
        self.assertIn("tag_1", help_text)

        self.assertEqual("", h(TDerived.method_2))
        self.assertEqual("", h(derived_obj.method_2))

        # method_3 is only mentioned in the base class, but should
        # be present in derived class help
        help_text = h(TDerived.method_3)
        self.assertEqual(help_text, h(derived_obj.method_3))

        self.assertIn("Some more method_3 detail, but no tags at all.", help_text)

        self.assertIn("misc", help_text)

    def test_derived_classes(self):
        """Check that help data for derived class contains info from base classes."""

        @h_doc
        class TClass1:
            """class 1 summary."""

            def method_1(self, some_arg_c1_m1):
                """description of method 1 in class 1.

                c1 m1 body

                """
                return some_arg_c1_m1

        @h_doc
        class TClass2:
            """class 2 summary."""

            def method_2(self, some_arg_c2_m2):
                """description of method 2 in class 2.

                c2 m2 body
                """
                return some_arg_c2_m2

        @h_doc
        class TDerived(TClass1, TClass2):
            """derived class summary."""

            def method_1(self, some_arg_cd_m1):
                """overridden method 1 summary

                cd m1 body
                """
                return some_arg_cd_m1

        # for tests prepare version of 'h' which does not print but return
        # help text
        h = HCommand()._make_help_text

        help_text = h(TDerived)

        self.assertIn('method_1', help_text)
        self.assertIn(
            'method_2', help_text,
            "this method is defined in base class only, but is decorated "
            "with 'h_doc', so it must be present in h-doc data for the "
            "derived class")

        self.assertIn(
            'some_arg_cd_m1', help_text,
            "method_1 was redefined in the derived class, so the h-doc for "
            "this method should be created based on the derived version "
            "(some_arg_cd_m1 is the name of argument of derived version)"
        )


class TestMethodNotes(unittest.TestCase):
    """Test 'method-notes' - information available for bound methods.

    h(object.method) can produce more info than h(some_calss.mehod) - f.e. for
    some objects the method may be available, for other objects (even objects
    of the same class!) the method may be not available. This info can be
    reported by the 'h' command.
    """

    def test_method_notes(self):
        """Test method-notes - information available for bound methods"""

        # 0. Prepare h-doc-capable class
        @h_doc
        class TClass:
            """Class with 'method-notes' functionality."""

            # such class attributes should not break hdocs
            SOME_CLASS_ATTR = {1:1, 2:2}
            SOME_TYPE = namedtuple('user', ['id', 'bloodtype'])

            def __init__(self):
                self.allow_method = True
                self.note_short = "note_short_allowed"
                self.note_line = "note_line_allowed"

            def the_method(self, some_arg):
                """The method to test.

                Quite simple method.
                But text of it's h-doc help depends on object data!
                """
                return some_arg + 42

            def _get_hdoc_method_notes(self, bound_method, _c):
                """Method which produce 'notes' to be used by h-doc.

                Method is predefined and should not be reported by h command.

                #no_hdoc
                """
                assert self is bound_method.__self__
                assert hasattr(bound_method, '_h_doc')
                fmt = _c.text if self.allow_method else _c.warn
                return BoundMethodNotes(
                    is_available=self.allow_method,
                    note_short=CHText(fmt(self.note_short)),
                    note_line=CHText(fmt(self.note_line)),
                )

        # for tests prepare version of 'h' which does not print but return
        # help text
        h = HCommand()._make_help_text

        # 1. test h-doc generated for class
        help_text = h(TClass)

        self.assertIn('the_method', help_text)
        self.assertNotIn("_get_hdoc_method_notes", help_text)
        self.assertNotIn("note_short_allowed", help_text)
        self.assertNotIn("note_line_allowed", help_text)

        # 2. test h-doc denerated for object of the class
        tst_obj = TClass()
        help_text = h(tst_obj)

        self.assertIn('the_method', help_text)
        self.assertNotIn("_get_hdoc_method_notes", help_text)
        self.assertIn(
            "note_short_allowed", help_text,
            "help text for bound method tst_obj.the_method should include "
            "the short note generated for the bound method")

        # 3. test h-doc generated for the bound method
        help_text = h(tst_obj.the_method)

        self.assertIn('some_arg', help_text)
        self.assertIn(
            "note_short_allowed", help_text,
            "text of bound method notes should be included into h-doc "
            "produced for the bound method")
        self.assertIn(
            "note_line_allowed", help_text,
            "text of bound method notes should be included into h-doc "
            "produced for the bound method")

        # 4. check not available bound methods are not reported
        # by default for objects
        tst_obj = TClass()
        tst_obj.allow_method = False
        help_text = h(tst_obj)

        self.assertNotIn(
            'the_method', help_text,
            "'the_method' is not available in the 'tst_obj' instance, "
            "so it should be notreported in h-doc by default")


class TestHDocsHidden(unittest.TestCase):
    """Test that methods with 'hidden' h-docs are not present in class help."""

    def test_some_hidden_hdocs(self):
        """Test that methods with 'hidden' h-docs are not present in class help."""

        @h_doc(explicit_only=True)
        class TClass:
            """Class with several methods having different types of h_docs"""

            @h_doc
            def method_1(self):
                """Usual method with explicit h_doc."""
                pass

            def method_2(self):
                """Method with doc string, but w/o explicit h_doc decorator."""
                pass

            @h_doc(hidden=True)
            def method_3(self):
                """Mwthod with explicit h_doc, but the doc is hidden."""
                pass

        # for tests prepare version of 'h' which does not print but return
        # help text
        h = HCommand()._make_help_text

        # 1. analyze h-doc of the class
        help_text = h(TClass)

        self.assertIn("TClass", help_text, "class name must be present")
        self.assertIn(
            "method_1", help_text,
            "method with explicit h_doc should be present in class help")
        self.assertNotIn(
            "method_2", help_text,
            "h_doc for class was created with 'explicit_only' option. "
            "method_2 has no explicit h_doc, so it is not mentiond in "
            "help text")
        self.assertNotIn(
            "method_3", help_text,
            "method_3 has explicit h_doc, but it is 'hidden' -  so it is "
            "not mentiond in help text")

        # 2. analyze h_doc's of individual methods
        self.assertIn("method_1", h(TClass.method_1))
        self.assertEqual("", h(TClass.method_2))
        self.assertIn(
            "method_3", h(TClass.method_3),
            "h_doc of method_3 is hidden, so this method is not mentioned "
            "in class help text. But it is available for explicitely "
            "specified object")

        # 3. analyze h-doc of object
        obj = TClass()
        help_text = h(obj)
        self.assertIn(
            "method_1", help_text,
            "method with explicit h_doc should be present in obj help")
        self.assertNotIn(
            "method_2", help_text,
            "h_doc for class was created with 'explicit_only' option. "
            "method_2 has no explicit h_doc, so it is not mentiond in "
            "help text")
        self.assertNotIn(
            "method_3", help_text,
            "method_3 has explicit h_doc, but it is 'hidden' -  so it is "
            "not mentiond in help text")


class TestHDocAttributes(unittest.TestCase):
    """Test reporting attributes by hdoc."""

    def test_hdoc_attributes(self):
        """Test reporting attributes by hdoc."""
        @h_doc
        class TClass:
            """Class with several attributes to be reported by h_doc."""

            _HDOC_ATTRS = [
                ('c1_conn', 'connection to component 1'),
                ('sql_conn', 'connection to sql database'),
            ]

            @h_doc
            def method_1(self):
                """Usual method with explicit h_doc."""
                pass

        h = HCommand()._make_help_text
        hh = HCommand(HCommand._LEVEL_HH)._make_help_text

        # 1. analyze h-doc of the class
        help_text = h(TClass)
        self.assertNotIn('Object of', help_text)
        self.assertIn('c1_conn', help_text)
        self.assertIn('connection to component 1', help_text)
        self.assertIn('sql_conn', help_text)
        self.assertIn('connection to sql database', help_text)
        self.assertNotIn('<n/a>', help_text)

        help_text = hh(TClass)
        self.assertNotIn('Object of', help_text)
        self.assertIn('c1_conn', help_text)
        self.assertIn('connection to component 1', help_text)
        self.assertIn('sql_conn', help_text)
        self.assertIn('connection to sql database', help_text)
        self.assertNotIn('<n/a>', help_text)

        # 2. analize h-doc of the object
        obj = TClass()
        obj.sql_conn = 42  # c1_conn renains None => be reported by hh only

        help_text = h(obj)
        self.assertIn('Object of', help_text)
        self.assertNotIn('c1_conn', help_text)
        self.assertNotIn('connection to component 1', help_text)
        self.assertIn('sql_conn', help_text)
        self.assertIn('connection to sql database', help_text)
        self.assertNotIn('<n/a>', help_text)

        help_text = hh(obj)
        self.assertIn('Object of', help_text)
        self.assertIn('c1_conn', help_text)
        self.assertIn('connection to component 1', help_text)
        self.assertIn('sql_conn', help_text)
        self.assertIn('connection to sql database', help_text)
        self.assertIn('<n/a>', help_text)
