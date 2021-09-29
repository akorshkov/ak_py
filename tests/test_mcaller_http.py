"""Test MCallerHttp - base class for "method callers" of http methods."""

import unittest

from ak.conn_http import HttpConn
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
            return conn(
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
            return conn(
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
            return conn(
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
