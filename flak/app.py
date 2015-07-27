# -*- coding: utf-8 -*-

import os
import sys
from threading import Lock
from datetime import timedelta
from collections import Mapping, deque
from functools import update_wrapper

from werkzeug.datastructures import ImmutableDict
from werkzeug.routing import Map, Rule, RequestRedirect, BuildError
from werkzeug.exceptions import (HTTPException, InternalServerError,
                                 MethodNotAllowed, BadRequest,
                                 default_exceptions)

from . import json, cli
from .helpers import (locked_cached_property, _endpoint_from_view_func,
                      find_package, get_root_path)
from .wrappers import Request, Response
from .config import ConfigAttribute, Config
from .context import RequestContext, AppContext, Bucket
from .sessions import SecureCookieSessionInterface
from .signals import (context_created, context_teardown,
                      request_started, request_finished, request_exception)
from ._compat import (string_types, text_type, integer_types,
                      reraise, iterkeys)


_logger_lock = Lock()
_sentinel = object()


def _make_timedelta(value):
    if not isinstance(value, timedelta):
        return timedelta(seconds=value)
    return value


def setupmethod(f):
    return f


class Flak(object):
    """
    :param import_name: the name of the application package
    :param instance_path: An alternative instance path for the application.
                          By default the folder ``'instance'`` next to the
                          package or module is assumed to be the instance
                          path.
    :param instance_relative_config: if set to ``True`` relative filenames
                                     for loading the config are assumed to
                                     be relative to the instance path instead
                                     of the application root.
    :param root_path: Flak by default will automatically calculate the path
                      to the root of the application.  In certain situations
                      this cannot be achieved (for instance if the package
                      is a Python 3 namespace package) and needs to be
                      manually defined.
    """

    request_class = Request
    response_class = Response
    context_globals_class = Bucket
    config_class = Config
    json_encoder = json.JSONEncoder
    json_decoder = json.JSONDecoder
    url_rule_class = Rule
    test_client_class = None
    session_interface = SecureCookieSessionInterface()

    debug = ConfigAttribute('DEBUG')
    testing = ConfigAttribute('TESTING')
    secret_key = ConfigAttribute('SECRET_KEY')
    session_cookie_name = ConfigAttribute('SESSION_COOKIE_NAME')
    permanent_session_lifetime = ConfigAttribute('PERMANENT_SESSION_LIFETIME',
                                                 get_converter=_make_timedelta)
    use_x_sendfile = ConfigAttribute('USE_X_SENDFILE')
    logger_name = ConfigAttribute('LOGGER_NAME')

    default_config = ImmutableDict({
        'DEBUG':                                False,
        'TESTING':                              False,
        'PROPAGATE_EXCEPTIONS':                 None,
        'PRESERVE_CONTEXT_ON_EXCEPTION':        None,
        'SECRET_KEY':                           None,
        'PERMANENT_SESSION_LIFETIME':           timedelta(days=31),
        'USE_X_SENDFILE':                       False,
        'LOGGER_NAME':                          None,
        'LOGGER_HANDLER_POLICY':               'always',
        'SERVER_NAME':                          None,
        'APPLICATION_ROOT':                     None,
        'SESSION_COOKIE_NAME':                  'session',
        'SESSION_COOKIE_DOMAIN':                None,
        'SESSION_COOKIE_PATH':                  None,
        'SESSION_COOKIE_HTTPONLY':              True,
        'SESSION_COOKIE_SECURE':                False,
        'SESSION_REFRESH_EACH_REQUEST':         True,
        'MAX_CONTENT_LENGTH':                   None,
        'SEND_FILE_MAX_AGE_DEFAULT':            12 * 60 * 60,  # 12 hours
        'TRAP_BAD_REQUEST_ERRORS':              False,
        'TRAP_HTTP_EXCEPTIONS':                 False,
        'PREFERRED_URL_SCHEME':                 'http',
        'JSON_AS_ASCII':                        True,
        'JSON_SORT_KEYS':                       True,
        'JSONIFY_PRETTYPRINT_REGULAR':          True,
    })

    def __init__(self, import_name,
                 instance_path=None,
                 instance_relative_config=False,
                 root_path=None):

        self.import_name = import_name
        if root_path is None:
            root_path = get_root_path(self.import_name)
        self.root_path = root_path

        if instance_path is None:
            instance_path = self.auto_find_instance_path()
        elif not os.path.isabs(instance_path):
            instance_path = os.path.abspath(instance_path)

        self.config = self.make_config(instance_relative_config)
        self.cli = cli.CommandGroup(self)
        self.instance_path = instance_path
        self._logger = None
        self.logger_name = self.import_name
        self.url_map = Map()
        self.endpoints = {}
        self.error_handlers = {}
        self.url_build_error_handlers = []
        self.before_request_funcs = []
        self.after_request_funcs = []
        self.teardown_funcs = []
        self.url_value_preprocessors = []
        self.url_default_functions = []
        self.shell_context_processors = []

    @locked_cached_property
    def name(self):
        if self.import_name == '__main__':
            fn = getattr(sys.modules['__main__'], '__file__', None)
            if fn is None:
                return '__main__'
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    @property
    def propagate_exceptions(self):
        rv = self.config['PROPAGATE_EXCEPTIONS']
        if rv is not None:
            return rv
        return self.testing or self.debug

    @property
    def logger(self):
        if self._logger and self._logger.name == self.logger_name:
            return self._logger
        with _logger_lock:
            if self._logger and self._logger.name == self.logger_name:
                return self._logger
            from flak.log import create_logger
            self._logger = rv = create_logger(self)
            return rv

    def open_resource(self, resource, mode='rb'):
        if mode not in ('r', 'rb'):
            raise ValueError('Resources can only be opened for reading')
        return open(os.path.join(self.root_path, resource), mode)

    def make_config(self, instance_relative=False):
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        return self.config_class(root_path, self.default_config)

    def auto_find_instance_path(self):
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, 'instance')
        return os.path.join(prefix, 'var', self.name + '-instance')

    def open_instance_resource(self, resource, mode='rb'):
        return open(os.path.join(self.instance_path, resource), mode)

    def make_shell_context(self):
        rv = {'app': self}
        for processor in self.shell_context_processors:
            rv.update(processor())
        return rv

    def run(self, host='0.0.0.0', port=8088, debug=None, **options):
        from werkzeug.serving import run_simple
        server_name = self.config['SERVER_NAME']
        if server_name and ':' in server_name:
            port = int(server_name.rsplit(':', 1)[1])
        if debug is not None:
            self.debug = bool(debug)
        options.setdefault('use_reloader', self.debug)
        options.setdefault('use_debugger', self.debug)
        run_simple(host, port, self, **options)

    def test_client(self, use_cookies=True, **kwargs):
        cls = self.test_client_class
        if cls is None:
            from flak.testing import FlakClient as cls
        return cls(self, self.response_class, use_cookies=use_cookies, **kwargs)

    def open_session(self, cx):
        return self.session_interface.open_session(cx)

    def save_session(self, cx, response):
        return self.session_interface.save_session(cx, response)

    @setupmethod
    def add_url_rule(self, pattern, func, key=None, **options):
        if key is None:
            key = _endpoint_from_view_func(func)
        options['endpoint'] = key
        methods = options.pop('methods', None)

        # if the methods are not given and the func object knows its
        # methods we can use that instead.  If neither exists, we go with
        # a tuple of only ``GET`` as default.
        if methods is None:
            methods = getattr(func, 'methods', None) or ('GET',)
        if isinstance(methods, string_types):
            raise TypeError('Allowed methods have to be iterables of strings, '
                            'for example: @app.route(..., methods=["POST"])')
        methods = set(item.upper() for item in methods)
        required_methods = set(getattr(func, 'required_methods', ()))

        provide_automatic_options = getattr(func,
                                            'provide_automatic_options', None)

        if provide_automatic_options is None:
            if 'OPTIONS' not in methods:
                provide_automatic_options = True
                required_methods.add('OPTIONS')
            else:
                provide_automatic_options = False

        # Add the required methods now.
        methods |= required_methods

        rule = self.url_rule_class(pattern, methods=methods, **options)
        rule.provide_automatic_options = provide_automatic_options

        self.url_map.add(rule)
        if func is not None:
            orig = self.endpoints.get(key)
            if orig is not None and orig != func:
                raise AssertionError('View function mapping is overwriting an '
                                     'existing endpoint function: %s' % key)
            self.endpoints[key] = func

    def route(self, rule, **options):
        def decorator(f):
            key = options.pop('endpoint', None)
            self.add_url_rule(rule, f, key, **options)
            return f
        return decorator

    @setupmethod
    def endpoint(self, key):
        def decorator(f):
            self.endpoints[key] = f
            return f
        return decorator

    @staticmethod
    def _get_exc_class_and_code(exc_class_or_code):
        if isinstance(exc_class_or_code, integer_types):
            exc_class = default_exceptions[exc_class_or_code]
        else:
            exc_class = exc_class_or_code

        assert issubclass(exc_class, Exception)

        if issubclass(exc_class, HTTPException):
            return exc_class, exc_class.code
        else:
            return exc_class, None

    @setupmethod
    def errorhandler(self, code_or_exception):
        def decorator(f):
            self.register_error_handler(code_or_exception, f)
            return f
        return decorator

    @setupmethod
    def register_error_handler(self, code_or_exception, f):
        exc_class, code = self._get_exc_class_and_code(code_or_exception)
        handlers = self.error_handlers.setdefault(code, {})
        handlers[exc_class] = f

    @setupmethod
    def before_request(self, f):
        self.before_request_funcs.append(f)
        return f

    @setupmethod
    def after_request(self, f):
        self.after_request_funcs.append(f)
        return f

    @setupmethod
    def teardown(self, f):
        self.teardown_funcs.append(f)
        return f

    @setupmethod
    def shell_context_processor(self, f):
        self.shell_context_processors.append(f)
        return f

    @setupmethod
    def url_value_preprocessor(self, f):
        self.url_value_preprocessors.append(f)
        return f

    @setupmethod
    def url_defaults(self, f):
        self.url_default_functions.append(f)
        return f

    def _find_error_handler(self, e):
        exc_class, code = self._get_exc_class_and_code(type(e))

        def find_handler(handler_map):
            if not handler_map:
                return
            q = deque(exc_class.__mro__)
            done = set()
            while q:
                cls = q.popleft()
                if cls in done:
                    continue
                done.add(cls)
                handler = handler_map.get(cls)
                if handler is not None:
                    # cache for next time exc_class is raised
                    handler_map[exc_class] = handler
                    return handler
                q.extend(cls.__mro__)

        return find_handler(self.error_handlers.get(code))

    def handle_http_exception(self, cx, e):
        if e.code is None:
            return e
        handler = self._find_error_handler(e)
        if handler is None:
            return e
        return handler(cx, e)

    def trap_http_exception(self, e):
        if self.config['TRAP_HTTP_EXCEPTIONS']:
            return True
        if self.config['TRAP_BAD_REQUEST_ERRORS']:
            return isinstance(e, BadRequest)
        return False

    def handle_user_exception(self, cx, e):
        exc_type, exc_value, tb = sys.exc_info()
        assert exc_value is e
        # ensure not to trash sys.exc_info() at that point in case someone
        # wants the traceback preserved in handle_http_exception

        if isinstance(e, HTTPException) and not self.trap_http_exception(e):
            return self.handle_http_exception(cx, e)

        handler = self._find_error_handler(e)
        if handler is None:
            reraise(exc_type, exc_value, tb)
        return handler(cx, e)

    def handle_exception(self, cx, e):
        exc_type, exc_value, tb = sys.exc_info()
        request_exception.send(self, context=cx, exception=e)
        handler = self._find_error_handler(InternalServerError())

        if self.propagate_exceptions:
            if exc_value is e:
                reraise(exc_type, exc_value, tb)
            else:
                raise e

        self.log_exception(cx, (exc_type, exc_value, tb))
        if handler is None:
            return InternalServerError()
        return handler(cx, e)

    def log_exception(self, cx, exc_info):
        msg = 'Exception on %s [%s]' % (cx.request.path,
                                        cx.request.method)
        self.logger.error(msg, exc_info=exc_info)

    def raise_routing_exception(self, rq):
        if (not self.debug
                or not isinstance(rq.routing_exception, RequestRedirect)
                or rq.method in ('GET', 'HEAD', 'OPTIONS')):
            raise rq.routing_exception

        from .debughelpers import FormDataRoutingRedirect
        raise FormDataRoutingRedirect(rq)

    def make_default_options_response(self, cx):
        rv = self.response_class()
        rv.allow.update(cx.url_adapter.allowed_methods())
        return rv

    def should_ignore_error(self, cx, error):
        return False

    def make_response(self, cx, rv):
        """
        rv:
        response_class          returned unchanged
        text                    a response object is created with the
                                string as body (unicode as utf-8)
        function                called as WSGI application
                                and buffered as response object
        tuple                   (response, status, headers), or
                                (response, headers)
                                where `response` is any of the
                                types defined here, `status` is a string
                                or an integer and `headers` is a list or
                                a dictionary with header values
        """
        status_or_headers = headers = None
        if isinstance(rv, tuple):
            rv, status_or_headers, headers = rv + (None,) * (3 - len(rv))

        if rv is None:
            raise ValueError('View function did not return a response')

        if isinstance(status_or_headers, (dict, list)):
            headers, status_or_headers = status_or_headers, None

        if not isinstance(rv, self.response_class):
            # When we create a response object directly, we let the constructor
            # set the headers and status.  We do this because there can be
            # some extra logic involved when creating these objects with
            # specific values (like default content type selection).
            if isinstance(rv, (text_type, bytes, bytearray)):
                rv = self.response_class(rv, headers=headers,
                                         status=status_or_headers)
                headers = status_or_headers = None
            else:
                rv = self.response_class.force_type(rv, cx.request.environ)

        if status_or_headers is not None:
            if isinstance(status_or_headers, string_types):
                rv.status = status_or_headers
            else:
                rv.status_code = status_or_headers
        if headers:
            rv.headers.extend(headers)

        return rv

    def create_url_adapter(self, cx):
        server_name = self.config['SERVER_NAME']
        if cx.request is not None:
            return self.url_map.bind_to_environ(cx.request.environ,
                                                server_name=server_name)
        if server_name is not None:
            script_name = self.config['APPLICATION_ROOT'] or '/'
            url_scheme = self.config['PREFERRED_URL_SCHEME']
            return self.url_map.bind(server_name,
                                     script_name=script_name,
                                     url_scheme=url_scheme)

    def inject_url_defaults(self, cx, endpoint, values):
        for f in self.url_default_functions:
            f(cx, endpoint, values)

    def handle_url_build_error(self, cx, error, endpoint, values):
        exc_type, exc_value, tb = sys.exc_info()
        for handler in self.url_build_error_handlers:
            try:
                rv = handler(cx, error, endpoint, values)
                if rv is not None:
                    return rv
            except BuildError as e:
                # make error available outside except block (py3)
                error = e

        # At this point we want to reraise the exception.  If the error is
        # still the same one we can reraise it with the original traceback,
        # otherwise we raise it from here.
        if error is exc_value:
            reraise(exc_type, exc_value, tb)
        raise error

    def preprocess_request(self, cx):
        rq = cx.request
        for f in self.url_value_preprocessors:
            f(cx, rq.endpoint, rq.view_args)

        for f in self.before_request_funcs:
            rv = f(cx)

            if rv is not None:
                return rv

    def process_response(self, cx, response):
        cx.process_response(response)
        for f in reversed(self.after_request_funcs):
            response = f(cx, response)
        self.save_session(cx, response)
        return response

    def do_teardown(self, cx, exc=_sentinel):
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        for f in reversed(self.teardown_funcs):
            f(cx, exc)
        context_teardown.send(self, context=cx, exception=exc)

    def build_request(self, environ):
        rq = self.request_class(environ)
        rq.max_content_length = self.config['MAX_CONTENT_LENGTH'] or None
        rq.debug = self.config.get('DEBUG', False)
        return rq

    def new_context(self, rq=None):
        if rq is None:
            cx = AppContext(self)
        else:
            cx = RequestContext(self, rq)
        context_created.send(self, context=cx)
        return cx

    def test_context(self, *args, **kwargs):
        from flak.testing import make_test_environ_builder
        builder = make_test_environ_builder(self, *args, **kwargs)
        try:
            rq = self.build_request(builder.get_environ())
            return self.new_context(rq)
        finally:
            builder.close()

    def wsgi_app(self, environ, start_response):
        rq = self.build_request(environ)
        cx = self.new_context(rq)
        error = None
        try:
            try:
                response = self.full_dispatch_request(cx)
            except Exception as e:
                error = e
                response = self.make_response(cx, self.handle_exception(cx, e))
            return response(environ, start_response)
        finally:
            if self.should_ignore_error(cx, error):
                error = None
            cx.close(error)

    def full_dispatch_request(self, cx):
        try:
            request_started.send(self, context=cx)
            rv = self.preprocess_request(cx)
            if rv is None:
                rv = self.dispatch_request(cx)
        except Exception as e:
            rv = self.handle_user_exception(cx, e)
        rsp = self.make_response(cx, rv)
        rsp = self.process_response(cx, rsp)
        request_finished.send(self, context=cx, response=rsp)
        return rsp

    def dispatch_request(self, cx):
        rq = cx.request
        if rq.routing_exception is not None:
            self.raise_routing_exception(rq)
        auto_options = getattr(rq.url_rule, 'provide_automatic_options', False)
        if (auto_options and rq.method == 'OPTIONS'):
            return self.make_default_options_response(cx)
        f = self.endpoints[rq.url_rule.endpoint]
        return f(cx, **rq.view_args)

    __call__ = wsgi_app

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__, self.name)

