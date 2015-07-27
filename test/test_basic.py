# -*- coding: utf-8 -*-

import pytest
import re
import uuid
import time
import pickle
from datetime import datetime
from threading import Thread
from werkzeug.exceptions import BadRequest, NotFound, Forbidden
from werkzeug.http import parse_date
from werkzeug.routing import BuildError
import werkzeug.serving
import flak
from flak import Flak
from flak._compat import text_type

def test_options_work():
    app = Flak(__name__)

    @app.route('/', methods=['GET', 'POST'])
    def index(cx):
        return 'Hello World'
    rv = app.test_client().open('/', method='OPTIONS')
    assert sorted(rv.allow) == ['GET', 'HEAD', 'OPTIONS', 'POST']
    assert rv.data == b''


def test_options_on_multiple_rules():
    app = Flak(__name__)

    @app.route('/', methods=['GET', 'POST'])
    def index(cx):
        return 'Hello World'

    @app.route('/', methods=['PUT'])
    def index_put(cx):
        return 'Aha!'
    rv = app.test_client().open('/', method='OPTIONS')
    assert sorted(rv.allow) == ['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT']


def test_options_handling_disabled():
    app = Flak(__name__)

    def index(cx):
        return 'Hello World!'
    index.provide_automatic_options = False
    app.route('/')(index)
    rv = app.test_client().open('/', method='OPTIONS')
    assert rv.status_code == 405

    app = Flak(__name__)

    def index2(cx):
        return 'Hello World!'
    index2.provide_automatic_options = True
    app.route('/', methods=['OPTIONS'])(index2)
    rv = app.test_client().open('/', method='OPTIONS')
    assert sorted(rv.allow) == ['OPTIONS']


def test_request_dispatching():
    app = Flak(__name__)

    @app.route('/')
    def index(cx):
        return cx.request.method

    @app.route('/more', methods=['GET', 'POST'])
    def more(cx):
        return cx.request.method

    c = app.test_client()
    assert c.get('/').data == b'GET'
    rv = c.post('/')
    assert rv.status_code == 405
    assert sorted(rv.allow) == ['GET', 'HEAD', 'OPTIONS']
    rv = c.head('/')
    assert rv.status_code == 200
    assert not rv.data  # head truncates
    assert c.post('/more').data == b'POST'
    assert c.get('/more').data == b'GET'
    rv = c.delete('/more')
    assert rv.status_code == 405
    assert sorted(rv.allow) == ['GET', 'HEAD', 'OPTIONS', 'POST']


def test_disallow_string_for_allowed_methods():
    app = Flak(__name__)
    with pytest.raises(TypeError):
        @app.route('/', methods='GET POST')
        def index(cx):
            return "Hey"


def test_url_mapping():
    app = Flak(__name__)

    random_uuid4 = "7eb41166-9ebf-4d26-b771-ea3f54f8b383"

    def index(cx):
        return cx.request.method

    def more(cx):
        return cx.request.method

    def options(cx):
        return random_uuid4


    app.add_url_rule('/', index)
    app.add_url_rule('/more', more, methods=['GET', 'POST'])

    # Issue 1288: Test that automatic options are not added when non-uppercase 'options' in methods
    app.add_url_rule('/options', options, methods=['options'])

    c = app.test_client()
    assert c.get('/').data == b'GET'
    rv = c.post('/')
    assert rv.status_code == 405
    assert sorted(rv.allow) == ['GET', 'HEAD', 'OPTIONS']
    rv = c.head('/')
    assert rv.status_code == 200
    assert not rv.data  # head truncates
    assert c.post('/more').data == b'POST'
    assert c.get('/more').data == b'GET'
    rv = c.delete('/more')
    assert rv.status_code == 405
    assert sorted(rv.allow) == ['GET', 'HEAD', 'OPTIONS', 'POST']
    rv = c.open('/options', method='OPTIONS')
    assert rv.status_code == 200
    assert random_uuid4 in rv.data.decode("utf-8")


def test_werkzeug_routing():
    from werkzeug.routing import Submount, Rule
    app = Flak(__name__)
    app.url_map.add(Submount('/foo', [
        Rule('/bar', endpoint='bar'),
        Rule('/', endpoint='index')
    ]))

    def bar(cx):
        return 'bar'

    def index(cx):
        return 'index'

    app.endpoints['bar'] = bar
    app.endpoints['index'] = index

    c = app.test_client()
    assert c.get('/foo/').data == b'index'
    assert c.get('/foo/bar').data == b'bar'


def test_endpoint_decorator():
    from werkzeug.routing import Submount, Rule
    app = Flak(__name__)
    app.url_map.add(Submount('/foo', [
        Rule('/bar', endpoint='bar'),
        Rule('/', endpoint='index')
    ]))

    @app.endpoint('bar')
    def bar(cx):
        return 'bar'

    @app.endpoint('index')
    def index(cx):
        return 'index'

    c = app.test_client()
    assert c.get('/foo/').data == b'index'
    assert c.get('/foo/bar').data == b'bar'


def test_session():
    app = Flak(__name__)
    app.secret_key = 'testkey'

    @app.route('/set', methods=['POST'])
    def set(cx):
        cx.session['value'] = cx.request.form['value']
        return 'value set'

    @app.route('/get')
    def get(cx):
        return cx.session['value']

    c = app.test_client()
    assert c.post('/set', data={'value': '42'}).data == b'value set'
    assert c.get('/get').data == b'42'


def test_session_using_server_name():
    app = Flak(__name__)
    app.config.update(
        SECRET_KEY='foo',
        SERVER_NAME='example.com'
    )

    @app.route('/')
    def index(cx):
        cx.session['testing'] = 42
        return 'Hello World'
    rv = app.test_client().get('/', 'http://example.com/')
    assert 'domain=.example.com' in rv.headers['set-cookie'].lower()
    assert 'httponly' in rv.headers['set-cookie'].lower()


def test_session_using_server_name_and_port():
    app = Flak(__name__)
    app.config.update(
        SECRET_KEY='foo',
        SERVER_NAME='example.com:8080'
    )

    @app.route('/')
    def index(cx):
        cx.session['testing'] = 42
        return 'Hello World'
    rv = app.test_client().get('/', 'http://example.com:8080/')
    assert 'domain=.example.com' in rv.headers['set-cookie'].lower()
    assert 'httponly' in rv.headers['set-cookie'].lower()


def test_session_using_server_name_port_and_path():
    app = Flak(__name__)
    app.config.update(
        SECRET_KEY='foo',
        SERVER_NAME='example.com:8080',
        APPLICATION_ROOT='/foo'
    )

    @app.route('/')
    def index(cx):
        cx.session['testing'] = 42
        return 'Hello World'
    rv = app.test_client().get('/', 'http://example.com:8080/foo')
    assert 'domain=example.com' in rv.headers['set-cookie'].lower()
    assert 'path=/foo' in rv.headers['set-cookie'].lower()
    assert 'httponly' in rv.headers['set-cookie'].lower()


def test_session_using_application_root():

    class PrefixPathMiddleware(object):
        def __init__(self, app, prefix):
            self.app = app
            self.prefix = prefix
        def __call__(self, environ, start_response):
            environ['SCRIPT_NAME'] = self.prefix
            return self.app(environ, start_response)

    app = Flak(__name__)
    app.wsgi_app = PrefixPathMiddleware(app.wsgi_app, '/bar')
    app.config.update(
        SECRET_KEY='foo',
        APPLICATION_ROOT='/bar'
    )

    @app.route('/')
    def index(cx):
        cx.session['testing'] = 42
        return 'Hello World'
    rv = app.test_client().get('/', 'http://example.com:8080/')
    assert 'path=/bar' in rv.headers['set-cookie'].lower()


def test_session_using_session_settings():
    app = Flak(__name__)
    app.config.update(
        SECRET_KEY='foo',
        SERVER_NAME='www.example.com:8080',
        APPLICATION_ROOT='/test',
        SESSION_COOKIE_DOMAIN='.example.com',
        SESSION_COOKIE_HTTPONLY=False,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_PATH='/'
    )

    @app.route('/')
    def index(cx):
        cx.session['testing'] = 42
        return 'Hello World'
    rv = app.test_client().get('/', 'http://www.example.com:8080/test/')
    cookie = rv.headers['set-cookie'].lower()
    assert 'domain=.example.com' in cookie
    assert 'path=/' in cookie
    assert 'secure' in cookie
    assert 'httponly' not in cookie


def test_null_session():
    app = Flak(__name__)
    with app.test_context() as cx:
        assert cx.session.get('missing_key') is None
        cx.session['foo'] = 42
        assert cx.session.get('foo') is None


def test_session_expiration():
    permanent = True
    app = Flak(__name__)
    app.secret_key = 'testkey'

    @app.route('/')
    def index(cx):
        cx.session['test'] = 42
        cx.session.permanent = permanent
        return ''

    @app.route('/test')
    def test(cx):
        return text_type(cx.session.permanent)

    client = app.test_client()
    rv = client.get('/')
    assert 'set-cookie' in rv.headers
    match = re.search(r'\bexpires=([^;]+)(?i)', rv.headers['set-cookie'])
    expires = parse_date(match.group())
    expected = datetime.utcnow() + app.permanent_session_lifetime
    assert expires.year == expected.year
    assert expires.month == expected.month
    assert expires.day == expected.day

    rv = client.get('/test')
    assert rv.data == b'True'

    permanent = False
    rv = app.test_client().get('/')
    assert 'set-cookie' in rv.headers
    match = re.search(r'\bexpires=([^;]+)', rv.headers['set-cookie'])
    assert match is None


def test_session_stored_last():
    app = Flak(__name__)
    app.secret_key = 'development-key'

    @app.after_request
    def modify_session(cx, response):
        cx.session['foo'] = 42
        return response

    @app.route('/')
    def dump_session_contents(cx):
        return repr(cx.session.get('foo'))

    c = app.test_client()
    assert c.get('/').data == b'None'
    assert c.get('/').data == b'42'


def test_session_special_types():
    app = Flak(__name__)
    app.secret_key = 'development-key'
    now = datetime.utcnow().replace(microsecond=0)
    the_uuid = uuid.uuid4()

    @app.after_request
    def modify_session(cx, response):
        cx.session['u'] = the_uuid
        cx.session['dt'] = now
        cx.session['b'] = b'\xff'
        cx.session['t'] = (1, 2, 3)
        return response

    @app.route('/')
    def dump_session_contents(cx):
        return pickle.dumps(dict(cx.session))

    c = app.test_client()
    c.get('/')
    rv = pickle.loads(c.get('/').data)
    assert rv['dt'] == now
    assert rv['u'] == the_uuid
    assert rv['b'] == b'\xff'
    assert type(rv['b']) == bytes
    assert rv['t'] == (1, 2, 3)


def test_session_cookie_setting():
    app = Flak(__name__)
    app.secret_key = 'dev key'
    is_permanent = True

    @app.route('/bump')
    def bump(cx):
        rv = cx.session['foo'] = cx.session.get('foo', 0) + 1
        cx.session.permanent = is_permanent
        return str(rv)

    @app.route('/read')
    def read(cx):
        return str(cx.session.get('foo', 0))

    def run_test(expect_header):
        with app.test_client() as c:
            assert c.get('/bump').data == b'1'
            assert c.get('/bump').data == b'2'
            assert c.get('/bump').data == b'3'

            rv = c.get('/read')
            set_cookie = rv.headers.get('set-cookie')
            assert (set_cookie is not None) == expect_header
            assert rv.data == b'3'

    is_permanent = True
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True
    run_test(expect_header=True)

    is_permanent = True
    app.config['SESSION_REFRESH_EACH_REQUEST'] = False
    run_test(expect_header=False)

    is_permanent = False
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True
    run_test(expect_header=False)

    is_permanent = False
    app.config['SESSION_REFRESH_EACH_REQUEST'] = False
    run_test(expect_header=False)


def test_request_processing():
    app = Flak(__name__)
    evts = []

    @app.before_request
    def before_request(cx):
        evts.append('before')

    @app.after_request
    def after_request(cx, response):
        response.data += b'|after'
        evts.append('after')
        return response

    @app.route('/')
    def index(cx):
        assert 'before' in evts
        assert 'after' not in evts
        return 'request'
    assert 'after' not in evts
    rv = app.test_client().get('/').data
    assert 'after' in evts
    assert rv == b'request|after'


def test_request_preprocessing_early_return():
    app = Flak(__name__)
    evts = []

    @app.before_request
    def before_request1(cx):
        evts.append(1)

    @app.before_request
    def before_request2(cx):
        evts.append(2)
        return "hello"

    @app.before_request
    def before_request3(cx):
        evts.append(3)
        return "bye"

    @app.route('/')
    def index(cx):
        evts.append('index')
        return "damnit"

    rv = app.test_client().get('/').data.strip()
    assert rv == b'hello'
    assert evts == [1, 2]


def test_after_request_processing():
    app = Flak(__name__)

    @app.route('/')
    def index(cx):
        @cx.after_request
        def foo(response):
            response.headers['X-Foo'] = 'a header'
            return response
        return 'Test'
    c = app.test_client()
    resp = c.get('/')
    assert resp.status_code == 200
    assert resp.headers['X-Foo'] == 'a header'


def test_teardown_request_handler():
    called = []
    app = Flak(__name__)

    @app.teardown
    def teardown(cx, exc):
        called.append(True)
        return "Ignored"

    @app.route('/')
    def root(cx):
        return "Response"
    rv = app.test_client().get('/')
    assert rv.status_code == 200
    assert b'Response' in rv.data
    assert len(called) == 1


def test_teardown_request_handler_debug_mode():
    called = []
    app = Flak(__name__)

    @app.teardown
    def teardown(cx, exc):
        called.append(True)
        return "Ignored"

    @app.route('/')
    def root(cx):
        return "Response"
    rv = app.test_client().get('/')
    assert rv.status_code == 200
    assert b'Response' in rv.data
    assert len(called) == 1


def test_teardown_request_handler_error():
    called = []
    app = Flak(__name__)
    app.config['LOGGER_HANDLER_POLICY'] = 'never'

    @app.teardown
    def teardown_request1(cx, exc):
        assert type(exc) == ZeroDivisionError
        called.append(True)
        # This raises a new error and blows away sys.exc_info(), so we can
        # test that all teardown_requests get passed the same original
        # exception.
        try:
            raise TypeError()
        except:
            pass

    @app.teardown
    def teardown_request2(cx, exc):
        assert type(exc) == ZeroDivisionError
        called.append(True)
        # This raises a new error and blows away sys.exc_info(), so we can
        # test that all teardown_requests get passed the same original
        # exception.
        try:
            raise TypeError()
        except:
            pass

    @app.route('/')
    def fails(cx):
        1 // 0
    rv = app.test_client().get('/')
    assert rv.status_code == 500
    assert b'Internal Server Error' in rv.data
    assert len(called) == 2


def test_before_after_request_order():
    called = []
    app = Flak(__name__)

    @app.before_request
    def before1(cx):
        called.append(1)

    @app.before_request
    def before2(cx):
        called.append(2)

    @app.after_request
    def after1(cx, response):
        called.append(4)
        return response

    @app.after_request
    def after2(cx, response):
        called.append(3)
        return response

    @app.teardown
    def finish1(cx, exc):
        called.append(6)

    @app.teardown
    def finish2(cx, exc):
        called.append(5)

    @app.route('/')
    def index(cx):
        return '42'
    rv = app.test_client().get('/')
    assert rv.data == b'42'
    assert called == [1, 2, 3, 4, 5, 6]


def test_error_handling():
    app = Flak(__name__)
    app.config['LOGGER_HANDLER_POLICY'] = 'never'

    @app.errorhandler(404)
    def not_found(cx, e):
        return 'not found', 404

    @app.errorhandler(500)
    def internal_server_error(cx, e):
        return 'internal server error', 500

    @app.errorhandler(Forbidden)
    def forbidden(cx, e):
        return 'forbidden', 403

    @app.route('/')
    def index(cx):
        flak.abort(404)

    @app.route('/error')
    def error(cx):
        1 // 0

    @app.route('/forbidden')
    def error2(cx):
        flak.abort(403)
    c = app.test_client()
    rv = c.get('/')
    assert rv.status_code == 404
    assert rv.data == b'not found'
    rv = c.get('/error')
    assert rv.status_code == 500
    assert b'internal server error' == rv.data
    rv = c.get('/forbidden')
    assert rv.status_code == 403
    assert b'forbidden' == rv.data


def test_before_request_and_routing_errors():
    app = Flak(__name__)

    @app.before_request
    def attach_something(cx):
        cx.something = 'value'

    @app.errorhandler(404)
    def return_something(cx, error):
        return cx.something, 404
    rv = app.test_client().get('/')
    assert rv.status_code == 404
    assert rv.data == b'value'


def test_user_error_handling():
    class MyException(Exception):
        pass

    app = Flak(__name__)

    @app.errorhandler(MyException)
    def handle_my_exception(cx, e):
        assert isinstance(e, MyException)
        return '42'

    @app.route('/')
    def index(cx):
        raise MyException()

    c = app.test_client()
    assert c.get('/').data == b'42'


def test_http_error_subclass_handling():
    class ForbiddenSubclass(Forbidden):
        pass

    app = Flak(__name__)

    @app.errorhandler(ForbiddenSubclass)
    def handle_forbidden_subclass(cx, e):
        assert isinstance(e, ForbiddenSubclass)
        return 'banana'

    @app.errorhandler(403)
    def handle_forbidden_subclass(cx, e):
        assert not isinstance(e, ForbiddenSubclass)
        assert isinstance(e, Forbidden)
        return 'apple'

    @app.route('/1')
    def index1(cx):
        raise ForbiddenSubclass()

    @app.route('/2')
    def index2(cx):
        flak.abort(403)

    @app.route('/3')
    def index3(cx):
        raise Forbidden()

    c = app.test_client()
    assert c.get('/1').data == b'banana'
    assert c.get('/2').data == b'apple'
    assert c.get('/3').data == b'apple'


def test_trapping_of_bad_request_key_errors():
    app = Flak(__name__)
    app.testing = True

    @app.route('/fail')
    def fail(cx):
        cx.request.form['missing_key']
    c = app.test_client()
    assert c.get('/fail').status_code == 400

    app.config['TRAP_BAD_REQUEST_ERRORS'] = True
    c = app.test_client()
    try:
        c.get('/fail')
    except KeyError as e:
        assert isinstance(e, BadRequest)
    else:
        assert False, 'Expected exception'


def test_trapping_of_all_http_exceptions():
    app = Flak(__name__)
    app.testing = True
    app.config['TRAP_HTTP_EXCEPTIONS'] = True

    @app.route('/fail')
    def fail(cx):
        flak.abort(404)

    c = app.test_client()
    with pytest.raises(NotFound):
        c.get('/fail')


def test_enctype_debug_helper():
    from flak.debughelpers import DebugFilesKeyError
    app = Flak(__name__)
    app.debug = True

    @app.route('/fail', methods=['POST'])
    def index(cx):
        return cx.request.files['foo'].filename

    with app.test_client() as c:
        try:
            c.post('/fail', data={'foo': 'index.txt'})
        except DebugFilesKeyError as e:
            assert 'no file contents were transmitted' in str(e)
            assert 'This was submitted: "index.txt"' in str(e)
        else:
            assert False, 'Expected exception'


def test_response_creation():
    app = Flak(__name__)

    @app.route('/unicode')
    def from_unicode(cx):
        return u'Hällo Wörld'

    @app.route('/string')
    def from_string(cx):
        return u'Hällo Wörld'.encode('utf-8')

    @app.route('/args')
    def from_tuple(cx):
        return 'Meh', 400, {
            'X-Foo': 'Testing',
            'Content-Type': 'text/plain; charset=utf-8'
        }

    @app.route('/two_args')
    def from_two_args_tuple(cx):
        return 'Hello', {
            'X-Foo': 'Test',
            'Content-Type': 'text/plain; charset=utf-8'
        }

    @app.route('/args_status')
    def from_status_tuple(cx):
        return 'Hi, status!', 400

    @app.route('/args_header')
    def from_response_instance_status_tuple(cx):
        return flak.Response('Hello world', 404), {
            "X-Foo": "Bar",
            "X-Bar": "Foo"
        }

    c = app.test_client()
    assert c.get('/unicode').data == u'Hällo Wörld'.encode('utf-8')
    assert c.get('/string').data == u'Hällo Wörld'.encode('utf-8')
    rv = c.get('/args')
    assert rv.data == b'Meh'
    assert rv.headers['X-Foo'] == 'Testing'
    assert rv.status_code == 400
    assert rv.mimetype == 'text/plain'
    rv = c.get('/two_args')
    assert rv.data == b'Hello'
    assert rv.headers['X-Foo'] == 'Test'
    assert rv.status_code == 200
    assert rv.mimetype == 'text/plain'
    rv = c.get('/args_status')
    assert rv.data == b'Hi, status!'
    assert rv.status_code == 400
    assert rv.mimetype == 'text/plain'
    rv = c.get('/args_header')
    assert rv.data == b'Hello world'
    assert rv.headers['X-Foo'] == 'Bar'
    assert rv.headers['X-Bar'] == 'Foo'
    assert rv.status_code == 404


def test_make_response():
    app = Flak(__name__)
    with app.test_context() as cx:
        rv = cx.make_response()
        assert rv.status_code == 200
        assert rv.data == b''
        assert rv.mimetype == 'text/plain'

        rv = cx.make_response('Awesome')
        assert rv.status_code == 200
        assert rv.data == b'Awesome'
        assert rv.mimetype == 'text/plain'

        rv = cx.make_response('W00t', 404)
        assert rv.status_code == 404
        assert rv.data == b'W00t'
        assert rv.mimetype == 'text/plain'


def test_make_response_with_response_instance():
    app = Flak(__name__)
    with app.test_context() as cx:
        rv = cx.make_response(cx.jsonify({'msg': 'W00t'}), 400)
        assert rv.status_code == 400
        assert rv.data == b'{\n  "msg": "W00t"\n}\n'
        assert rv.mimetype == 'application/json'

        rv = cx.make_response(flak.Response(''), 400)
        assert rv.status_code == 400
        assert rv.data == b''
        assert rv.mimetype == 'text/plain'

        rsp = flak.Response('', headers={'Content-Type': 'text/html'})
        rv = cx.make_response(rsp, 400, [('X-Foo', 'bar')])
        assert rv.status_code == 400
        assert rv.headers['Content-Type'] == 'text/html'
        assert rv.headers['X-Foo'] == 'bar'


def test_jsonify_no_prettyprint():
    app = Flak(__name__)
    app.config.update({"JSONIFY_PRETTYPRINT_REGULAR": False})
    with app.test_context() as cx:
        json = b'{"msg":{"submsg":"W00t"},"msg2":"foobar"}\n'
        obj = {"msg": {"submsg": "W00t"},
               "msg2": "foobar"}
        rv = cx.make_response(cx.jsonify(obj), 200)
        assert rv.data == json


def test_jsonify_prettyprint():
    app = Flak(__name__)
    app.config.update({"JSONIFY_PRETTYPRINT_REGULAR": True})
    with app.test_context() as cx:
        compressed = {"msg":{"submsg":"W00t"},"msg2":"foobar"}
        expect =\
            b'{\n  "msg": {\n    "submsg": "W00t"\n  }, \n  "msg2": "foobar"\n}\n'

        rv = cx.make_response(cx.jsonify(compressed), 200)
        assert rv.data == expect


def test_url_generation():
    app = Flak(__name__)

    @app.route('/hello/<name>', methods=['POST'])
    def hello(cx):
        pass
    with app.test_context() as cx:
        assert cx.url_for('hello', name='test x') == '/hello/test%20x'
        assert cx.url_for('hello', name='test x', _external=True) == \
            'http://localhost/hello/test%20x'


def test_build_error_handler():
    app = Flak(__name__)

    # Test base case, a URL which results in a BuildError.
    with app.test_context() as cx:
        pytest.raises(BuildError, cx.url_for, 'spam')

    # Verify the error is re-raised if not the current exception.
    try:
        with app.test_context() as cx:
            cx.url_for('spam')
    except BuildError as err:
        error = err
    try:
        raise RuntimeError('Test case where BuildError is not current.')
    except RuntimeError:
        pytest.raises(BuildError, app.handle_url_build_error,
                      None, error, 'spam', {})

    # Test a custom handler.
    def handler(cx, error, endpoint, values):
        # Just a test.
        return '/test_handler/'
    app.url_build_error_handlers.append(handler)
    with app.test_context() as cx:
        assert cx.url_for('spam') == '/test_handler/'


def test_build_error_handler_reraise():
    app = Flak(__name__)
    # Test a custom handler which reraises the BuildError
    def handler_raises_build_error(cx, error, endpoint, values):
        raise error
    app.url_build_error_handlers.append(handler_raises_build_error)

    with app.test_context() as cx:
        pytest.raises(BuildError, cx.url_for, 'not.existing')


def test_custom_converters():
    from werkzeug.routing import BaseConverter

    class ListConverter(BaseConverter):
        def to_python(self, value):
            return value.split(',')
        def to_url(self, value):
            base_to_url = super(ListConverter, self).to_url
            return ','.join(base_to_url(x) for x in value)

    app = Flak(__name__)
    app.url_map.converters['list'] = ListConverter

    @app.route('/<list:args>')
    def index(cx, args):
        return '|'.join(args)
    c = app.test_client()
    assert c.get('/1,2,3').data == b'1|2|3'


def test_none_response():
    app = Flak(__name__)

    @app.route('/')
    def test(cx):
        return None
    try:
        app.test_client().get('/')
    except ValueError as e:
        assert str(e) == 'View function did not return a response'
        pass
    else:
        assert "Expected ValueError"


def test_test_app_proper_environ():
    app = Flak(__name__)
    app.config.update(SERVER_NAME='localhost.localdomain:5000')

    @app.route('/')
    def index(cx):
        return 'Foo'

    @app.route('/', subdomain='foo')
    def subdomain(cx):
        return 'Foo SubDomain'

    rv = app.test_client().get('/')
    assert rv.data == b'Foo'

    rv = app.test_client().get('/', 'http://localhost.localdomain:5000')
    assert rv.data == b'Foo'

    rv = app.test_client().get('/', 'https://localhost.localdomain:5000')
    assert rv.data == b'Foo'

    app.config.update(SERVER_NAME='localhost.localdomain')
    rv = app.test_client().get('/', 'https://localhost.localdomain')
    assert rv.data == b'Foo'

    app.config.update(SERVER_NAME='localhost.localdomain:443')
    rv = app.test_client().get('/', 'https://localhost.localdomain')
    assert rv.status_code == 404

    app.config.update(SERVER_NAME='localhost.localdomain')
    rv = app.test_client().get('/', 'http://foo.localhost')
    assert rv.status_code == 404

    rv = app.test_client().get('/', 'http://foo.localhost.localdomain')
    assert rv.data == b'Foo SubDomain'


def test_exception_propagation():
    def apprunner(config_key):
        app = Flak(__name__)
        app.config['LOGGER_HANDLER_POLICY'] = 'never'

        @app.route('/')
        def index(cx):
            1 // 0
        c = app.test_client()
        if config_key is not None:
            app.config[config_key] = True
            try:
                c.get('/')
            except Exception:
                pass
            else:
                assert False, 'expected exception'
        else:
            assert c.get('/').status_code == 500

    # we have to run this test in an isolated thread because if the
    # debug flag is set to true and an exception happens the context is
    # not torn down.  This causes other tests that run after this fail
    # when they expect no exception on the stack.
    for config_key in 'TESTING', 'PROPAGATE_EXCEPTIONS', 'DEBUG', None:
        t = Thread(target=apprunner, args=(config_key,))
        t.start()
        t.join()


def test_max_content_length():
    app = Flak(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 64

    @app.before_request
    def always_first(cx):
        cx.request.form['myfile']
        assert False

    @app.route('/accept', methods=['POST'])
    def accept_file(cx):
        cx.request.form['myfile']
        assert False

    @app.errorhandler(413)
    def catcher(cx, error):
        return '42'

    c = app.test_client()
    rv = c.post('/accept', data={'myfile': 'foo' * 100})
    assert rv.data == b'42'


def test_url_processors():
    app = Flak(__name__)

    @app.url_defaults
    def add_language_code(cx, endpoint, values):
        if cx.lang_code is not None and \
           app.url_map.is_endpoint_expecting(endpoint, 'lang_code'):
            values.setdefault('lang_code', cx.lang_code)

    @app.url_value_preprocessor
    def pull_lang_code(cx, endpoint, values):
        cx.lang_code = values.pop('lang_code', None)

    @app.route('/<lang_code>/')
    def index(cx):
        return cx.url_for('about')

    @app.route('/<lang_code>/about')
    def about(cx):
        return cx.url_for('something_else')

    @app.route('/foo')
    def something_else(cx):
        return cx.url_for('about', lang_code='en')

    c = app.test_client()

    assert c.get('/de/').data == b'/de/about'
    assert c.get('/de/about').data == b'/foo'
    assert c.get('/foo').data == b'/en/about'


def test_nonascii_pathinfo():
    app = Flak(__name__)

    @app.route(u'/киртест')
    def index(cx):
        return 'Hello World!'

    c = app.test_client()
    rv = c.get(u'/киртест')
    assert rv.data == b'Hello World!'


def test_routing_redirect_debugging():
    app = Flak(__name__)
    app.debug = True

    @app.route('/foo/', methods=['GET', 'POST'])
    def foo(cx):
        return 'success'
    with app.test_client() as c:
        try:
            c.post('/foo', data={})
        except AssertionError as e:
            assert 'http://localhost/foo/' in str(e)
            assert ('Make sure to directly send '
                    'your POST-request to this URL') in str(e)
        else:
            assert False, 'Expected exception'

        rv = c.get('/foo', data={}, follow_redirects=True)
        assert rv.data == b'success'

    app.debug = False
    with app.test_client() as c:
        rv = c.post('/foo', data={}, follow_redirects=True)
        assert rv.data == b'success'


def test_route_decorator_custom_endpoint():
    app = Flak(__name__)
    app.debug = True

    @app.route('/foo/')
    def foo(cx):
        return cx.request.endpoint

    @app.route('/bar/', endpoint='bar')
    def for_bar(cx):
        return cx.request.endpoint

    @app.route('/bar/123', endpoint='123')
    def for_bar_foo(cx):
        return cx.request.endpoint

    with app.test_context() as cx:
        assert cx.url_for('foo') == '/foo/'
        assert cx.url_for('bar') == '/bar/'
        assert cx.url_for('123') == '/bar/123'

    c = app.test_client()
    assert c.get('/foo/').data == b'foo'
    assert c.get('/bar/').data == b'bar'
    assert c.get('/bar/123').data == b'123'


def test_preserve_only_once():
    app = Flak(__name__)
    app.debug = True

    @app.route('/fail')
    def fail_func(cx):
        1 // 0

    with app.test_client() as c:
        for x in range(3):
            with pytest.raises(ZeroDivisionError):
                c.get('/fail')

        assert c.captured_context is not None


def test_preserve_remembers_exception():
    app = Flak(__name__)
    app.debug = True
    errors = []

    @app.route('/fail')
    def fail_func(cx):
        1 // 0

    @app.route('/success')
    def success_func(cx):
        return 'Okay'

    @app.teardown
    def teardown_handler(cx, exc):
        errors.append(exc)

    c = app.test_client()

    # After this failure we did not yet call the teardown handler
    with pytest.raises(ZeroDivisionError):
        c.get('/fail')
    #assert errors == []
    assert len(errors) == 1

    # But this request triggers it, and it's an error
    c.get('/success')
    assert len(errors) == 2

    # At this point another request does nothing.
    c.get('/success')
    assert len(errors) == 3
    assert errors[1] is None


def test_get_method_on_g():
    app = Flak(__name__)

    with app.new_context() as cx:
        assert cx.globals.get('x') is None
        assert cx.globals.get('x', 11) == 11
        cx.globals.x = 42
        assert cx.globals.get('x') == 42
        assert cx.globals.x == 42


def test_g_iteration_protocol():
    app = Flak(__name__)

    with app.new_context() as cx:
        cx.globals.foo = 23
        cx.globals.bar = 42
        assert 'foo' in cx.globals
        assert 'foos' not in cx.globals
        assert sorted(cx.globals) == ['bar', 'foo']


def test_subdomain_basic_support():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'localhost'

    @app.route('/')
    def normal_index(cx):
        return 'normal index'

    @app.route('/', subdomain='test')
    def test_index(cx):
        return 'test index'

    c = app.test_client()
    rv = c.get('/', 'http://localhost/')
    assert rv.data == b'normal index'

    rv = c.get('/', 'http://test.localhost/')
    assert rv.data == b'test index'


def test_subdomain_matching():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'localhost'

    @app.route('/', subdomain='<user>')
    def index(cx, user):
        return 'index for %s' % user

    c = app.test_client()
    rv = c.get('/', 'http://mitsuhiko.localhost/')
    assert rv.data == b'index for mitsuhiko'


def test_subdomain_matching_with_ports():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'localhost:3000'

    @app.route('/', subdomain='<user>')
    def index(cx, user):
        return 'index for %s' % user

    c = app.test_client()
    rv = c.get('/', 'http://mitsuhiko.localhost:3000/')
    assert rv.data == b'index for mitsuhiko'


def test_multi_route_rules():
    app = Flak(__name__)

    @app.route('/')
    @app.route('/<test>/')
    def index(cx, test='a'):
        return test

    rv = app.test_client().open('/')
    assert rv.data == b'a'
    rv = app.test_client().open('/b/')
    assert rv.data == b'b'


def test_multi_route_class_views():
    class View(object):

        def __init__(self, app):
            app.add_url_rule('/', self.index)
            app.add_url_rule('/<test>/', self.index)

        def index(self, cx, test='a'):
            return test

    app = Flak(__name__)
    View(app)
    rv = app.test_client().get('/')
    assert rv.data == b'a'
    rv = app.test_client().get('/b/')
    assert rv.data == b'b'


def test_run_defaults(monkeypatch):
    rv = {}

    def run_simple_mock(*args, **kwargs):
        rv['result'] = 'running...'

    app = Flak(__name__)
    monkeypatch.setattr(werkzeug.serving, 'run_simple', run_simple_mock)
    app.run()
    assert rv['result'] == 'running...'


def test_run_server_port(monkeypatch):
    rv = {}

    # Mocks werkzeug.serving.run_simple method
    def run_simple_mock(hostname, port, app, *args, **kwargs):
        rv['result'] = 'running on %s:%s ...' % (hostname, port)

    monkeypatch.setattr(werkzeug.serving, 'run_simple', run_simple_mock)
    hostname, port = 'localhost', 8000
    app = Flak(__name__)
    app.run(hostname, port, debug=True)
    assert rv['result'] == 'running on %s:%s ...' % (hostname, port)

