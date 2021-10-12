"""Test MCallerHttp - base class for "method callers" of http methods."""

import unittest

from ak.conn_http import HttpConn
from ak.hdoc import HCommand
from ak.mcaller_http import MCallerHttp, method_http

from .mock_http import mock_http


class TestMCallerHttp(unittest.TestCase):
    """Test functionality of MCallerHttp classes.

    MCallerHttp is a MethodCaller which wraps http requests.
    """

    class MethodsCollection1(MCallerHttp):
        """Collection of several http wrappers."""

        @method_http
        def call_it(self, param, arg):
            """sample http wrapper method."""
            conn = self.get_conn()
            return conn.post(
                "/my/test/path",
                params={'param': param},
                data={'arg': arg},
            )

    class MethodsCollection2(MCallerHttp):
        """Another collection of several http wrappers."""

        @method_http("bauth")
        def call_it_another(self, param, arg):
            """sample http wrapper method."""
            conn = self.get_conn()
            return conn.post(
                "/my/test/another_path",
                params={'param': param},
                data={'arg': arg},
            )

    class MethodsCollection3(MCallerHttp):
        """Yet another http wrappers. These specify component."""

        @method_http(None, "componentA")
        def call_v3(self, param, arg):
            """sample http wrapper method."""
            conn = self.get_conn()
            return conn.post(
                "/my/test/another_path",
                params={'param': param},
                data={'arg': arg},
            )

        @method_http(None, "componentB")
        def call_v4(self, param, arg):
            """sample http wrapper method."""
            conn = self.get_conn()
            return conn.post(
                "/my/test/another_path",
                params={'param': param},
                data={'arg': arg},
            )

    def test_simple_http_mcaller(self):
        """Create an acual method caller and verify requests processesing."""

        class MyHttpCaller(self.MethodsCollection1, self.MethodsCollection2):
            """Combines two mix-ins into an actual method caller """
            def __init__(self, address):
                self.http_conn = HttpConn(address)

        # 1. create an actual caller
        my_caller = MyHttpCaller("http://dummy.com:8080")

        # 2. analyze details of the http requests sent
        # 2.1. check 'call_it' method
        intercepted_requests = []
        with mock_http(intercepted_requests):
            my_caller.call_it(25, 42)

        self.assertEqual(1, len(intercepted_requests))
        req = intercepted_requests[0]

        self.assertIn("dummy.com:8080/my/test/path", req.full_url)
        self.assertEqual(b'{"arg": 42}', req.data)

        # 2.2. check 'call_it_another' method
        with mock_http(intercepted_requests):
            my_caller.call_it_another(25, 42)

        self.assertEqual(2, len(intercepted_requests))
        req = intercepted_requests[-1]

        self.assertIn("dummy.com:8080/my/test/another_path", req.full_url)
        self.assertEqual(b'{"arg": 42}', req.data)

    def test_http_mcaller_components(self):
        """Test MCallerHttp when methods are assigned to components."""

        class MyCompHttpCaller(self.MethodsCollection1, self.MethodsCollection3):
            """Http methods caller with support of components."""
            def __init__(self, address):
                self.http_conn = HttpConn(address)
                # need to define this map for call_v3 method to work
                # (component is specified in it's metadata)
                self.http_prefixes = {
                    'componentA': '/cmpA/prefix',
                }

        # 1. create an actual caller
        my_caller = MyCompHttpCaller("http://dummy.com:8080")

        # 2. analyze details of the http requests sent
        # 2.1. check 'call_it' method. Component is not specified for this method
        # it should work as usual
        intercepted_requests = []
        with mock_http(intercepted_requests):
            my_caller.call_it(25, 42)

        self.assertEqual(1, len(intercepted_requests))
        req = intercepted_requests[0]

        self.assertIn("dummy.com:8080/my/test/path", req.full_url)
        self.assertEqual(b'{"arg": 42}', req.data)

        # 2.3. check 'call_v3' method. Path prefix is specified for it's
        # component, this prefix should be added to path during the call
        with mock_http(intercepted_requests):
            my_caller.call_v3(25, 42)

        self.assertEqual(2, len(intercepted_requests))
        req = intercepted_requests[-1]

        self.assertIn(
            "dummy.com:8080/cmpA/prefix/my/test/another_path", req.full_url)

    def test_http_mcsaller_hdoc(self):
        """Check 'h' command with MCallerHttp class and objects"""
        class MyCompHttpCaller(self.MethodsCollection1, self.MethodsCollection3):
            """Test class to test 'h' command."""
            def __init__(self, address):
                self.http_conn = HttpConn(address)
                self.http_prefixes = {
                    'componentA': '/cmpA/prefix',
                }

        h = HCommand()._make_help_text

        # verify help generated for class
        hdoc_class = h(MyCompHttpCaller)
        self.assertIn('call_it', hdoc_class, "method from MethodsCollection1")
        self.assertIn('call_v3', hdoc_class, "method from MethodsCollection3")
        self.assertIn('call_v4', hdoc_class, "method from MethodsCollection3")
        self.assertNotIn('call_it_r', hdoc_class)
        self.assertNotIn('call_v3_r', hdoc_class)
        self.assertNotIn('call_v4_r', hdoc_class)

        # verify that service methods are not included into help text
        for service_method in ['get_conn', 'get_mcaller_meta']:
            self.assertTrue(hasattr(MyCompHttpCaller, service_method))
            self.assertNotIn(service_method, hdoc_class)

        # verify help generated for individual methods in class
        self.assertIn('call_it', h(MyCompHttpCaller.call_it))
        self.assertIn('call_v3', h(MyCompHttpCaller.call_v3))
        self.assertIn('call_v4', h(MyCompHttpCaller.call_v4))

        # verify help generated even for 'hidden' methods in class
        self.assertIn('call_it', h(MyCompHttpCaller.call_it_r))
        self.assertIn('call_v3', h(MyCompHttpCaller.call_v3_r))
        self.assertIn('call_v4', h(MyCompHttpCaller.call_v4_r))

        # verify help generated for an object of class
        x = MyCompHttpCaller("https://some.address.org")
        hdoc_obj = h(x)

        self.assertIn('call_it', hdoc_obj, "method from MethodsCollection1")
        self.assertIn('call_v3', hdoc_obj, "method from MethodsCollection3")
        self.assertNotIn(
            'call_v4', hdoc_obj,
            "this mehod should not be present in help because it's "
            "unavailable in the object. Method requires http connection for"
            "component 'componentB', but the object has only connection "
            "to componentA")

        self.assertNotIn('call_it_r', hdoc_obj)
        self.assertNotIn('call_v3_r', hdoc_obj)

        # verify that service methods are not included into help text
        for service_method in ['get_conn', 'get_mcaller_meta']:
            self.assertTrue(hasattr(x, service_method))
            self.assertNotIn(service_method, hdoc_obj)
