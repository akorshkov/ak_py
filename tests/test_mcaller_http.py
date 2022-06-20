"""Test MCallerHttp - base class for "method callers" of http methods."""

import unittest

import base64

from ak.conn_http import BAuthConn
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

        @method_http("basic")
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
            pass

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
            _HTTP_PREFIX_MAP = {
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

        # make sure cloned caller works as well. The cloned caller
        # will use authorized connection
        cloned_caller = my_caller.clone(
            BAuthConn.Adapter('my_name', 'std_password'))

        intercepted_requests = []
        with mock_http(intercepted_requests):
            cloned_caller.call_it(25, 42)

        self.assertEqual(1, len(intercepted_requests))
        req = intercepted_requests[0]

        self.assertIn('Authorization', req.headers)
        auth_header = req.headers['Authorization']
        self.assertTrue(
            auth_header.startswith(b'Basic '),
            f"auth header is: {auth_header}")
        creds_str = base64.b64decode(auth_header[6:]).decode()
        self.assertIn('my_name', creds_str)
        self.assertIn('std_password', creds_str)

    def test_http_mcsaller_hdoc(self):
        """Check 'h' command with MCallerHttp class and objects"""
        class MyCompHttpCaller(self.MethodsCollection1, self.MethodsCollection3):
            """Test class to test 'h' command."""
            _HTTP_PREFIX_MAP = {
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

    def test_hdoc_auth_types_filtering(self):
        """Test 'h' command reporting methods with different auth types."""
        class MyHttpCaller(MCallerHttp):
            """Collection of several http methods."""
            @method_http
            def m1_no_auth(self):
                """method w/o explicitely specified auth type"""
                pass

            @method_http(None)
            def m2_no_auth_explicit(self):
                """method with explicitely specified None auth type"""
                pass

            @method_http('basic')
            def m3_bauth(self):
                """Method with basic auth type."""
                pass

            @method_http([None, 'basic'])
            def m4_bauth_or_no_auth(self):
                """method with basic or no auth"""
                pass

        h = HCommand()._make_help_text

        caller_no_auth = MyHttpCaller("https://some.address.fun")
        obj_descr = h(caller_no_auth)
        self.assertIn('m1_no_auth', obj_descr)
        self.assertIn('m2_no_auth_explicit', obj_descr)
        self.assertNotIn('m3_bauth', obj_descr)
        self.assertIn('m4_bauth_or_no_auth', obj_descr)

        caller_bauth = caller_no_auth.clone(
            BAuthConn.Adapter('my_name', 'my_password'))
        obj_descr = h(caller_bauth)
        self.assertNotIn('m1_no_auth', obj_descr)
        self.assertNotIn('m2_no_auth_explicit', obj_descr)
        self.assertIn('m3_bauth', obj_descr)
        self.assertIn('m4_bauth_or_no_auth', obj_descr)

class TestMCallerHttpMultipleComponents(unittest.TestCase):
    """Test http mcaller method which can call different components."""

    class MethodsCollection(MCallerHttp):
        """Collection of several http wrappers."""

        @method_http("basic", ["my_server", "my_server_frontend"])
        def call_it(self, arg):
            """Simulate situation, that 'my_server' component provides some,
            api method, but it is available via frontend api gateway also.
            """
            conn = self.get_conn()
            return conn.post(
                "/my/call/path",
                data={"arg": arg},
            )

    def test_success_calls_different_frontends(self):
        """Test successfull scenario of http call."""
        class MyHttpCaller(self.MethodsCollection):
            """Ready Http Caller."""
            _HTTP_PREFIX_MAP = {
                "my_server": "/prefix/my/server",
                "another_componets": "/other/prefix",
            }

        # 1. create an actual caller
        my_caller = MyHttpCaller("http://dummy.com:8080")

        # 2. make request
        intercepted_requests = []
        with mock_http(intercepted_requests):
            my_caller.call_it(4242)

        self.assertEqual(1, len(intercepted_requests))
        req = intercepted_requests[0]

        self.assertIn(
            "dummy.com:8080/prefix/my/server", req.full_url,
            "_HTTP_PREFIX_MAP['my_server'] must present in path")

    def test_components_conflict(self):
        """Test conflict situation."""
        class MyHttpCaller(self.MethodsCollection):
            """Ready Http Caller."""
            _HTTP_PREFIX_MAP = {
                "my_server": "/prefix/my/server",
                "my_server_frontend": "/api/",
            }

        # 1. create an actual caller
        my_caller = MyHttpCaller("http://dummy.com:8080")

        # 2. try to make request
        #
        # Method needs to call either "my_server" or "my_server_frontend"
        # component, the MyHttpCaller has both - can't make a request
        # because can't decide which http prefix to use.
        with self.assertRaises(AssertionError) as exc:
            my_caller.call_it(42)

        err_msg = str(exc.exception)
        self.assertIn("http method expects connection", err_msg)
        self.assertIn("my_server", err_msg)
        self.assertIn("my_server_frontend", err_msg)

    def test_no_matching_component(self):
        """Request fails because http prefix is not configured for component."""
        class MyHttpCaller(self.MethodsCollection):
            """Ready Http Caller."""
            _HTTP_PREFIX_MAP = {
                "some_component": "/prefix/my/server",
                "another_one": "/api/",
            }

        # 1. create an actual caller
        my_caller = MyHttpCaller("http://dummy.com:8080")

        # 2. try to make request
        #
        # Method needs to call either "my_server" or "my_server_frontend"
        # component, the MyHttpCaller has none of it.
        with self.assertRaises(AssertionError) as exc:
            my_caller.call_it(42)

        err_msg = str(exc.exception)
        self.assertIn("http method expects connection", err_msg)
        self.assertIn("my_server", err_msg)
        self.assertIn("my_server_frontend", err_msg)
