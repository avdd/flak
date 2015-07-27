# -*- coding: utf-8 -*-

import pytest
import flak
from flak import Flak

def test_basic_url_generation():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'localhost'
    app.config['PREFERRED_URL_SCHEME'] = 'https'

    @app.route('/')
    def index(cx):
        pass

    with app.new_context() as cx:
        rv = cx.url_for('index')
        assert rv == 'https://localhost/'

def test_url_generation_requires_server_name():
    app = Flak(__name__)
    with app.new_context() as cx:
        with pytest.raises(RuntimeError):
            cx.url_for('index')

def test_context_has_app():
    app = Flak(__name__)
    with app.test_context() as cx:
        assert cx.app is app

def test_new_context():
    app = Flak(__name__)
    with app.new_context() as cx:
        assert cx.app is app

def test_app_tearing_down():
    cleanup_stuff = []
    app = Flak(__name__)
    @app.teardown
    def cleanup(cx, exception):
        cleanup_stuff.append(exception)

    with app.new_context():
        pass

    assert cleanup_stuff == [None]

def test_app_tearing_down_with_previous_exception():
    cleanup_stuff = []
    app = Flak(__name__)
    @app.teardown
    def cleanup(cx, exception):
        cleanup_stuff.append(exception)

    try:
        raise Exception('dummy')
    except Exception:
        pass

    with app.new_context():
        pass

    assert cleanup_stuff == [None]

def test_app_tearing_down_with_handled_exception():
    cleanup_stuff = []
    app = Flak(__name__)
    @app.teardown
    def cleanup(cx, exception):
        cleanup_stuff.append(exception)

    with app.new_context():
        try:
            raise Exception('dummy')
        except Exception:
            pass

    assert cleanup_stuff == [None]

def test_app_context_globals_methods():
    app = Flak(__name__)
    with app.new_context() as cx:
        # get
        assert cx.globals.get('foo') is None
        assert cx.globals.get('foo', 'bar') == 'bar'
        # __contains__
        assert 'foo' not in cx.globals
        cx.globals.foo = 'bar'
        assert 'foo' in cx.globals
        # setdefault
        cx.globals.setdefault('bar', 'the cake is a lie')
        cx.globals.setdefault('bar', 'hello world')
        assert cx.globals.bar == 'the cake is a lie'
        # pop
        assert cx.globals.pop('bar') == 'the cake is a lie'
        with pytest.raises(KeyError):
            cx.globals.pop('bar')
        assert cx.globals.pop('bar', 'more cake') == 'more cake'
        # __iter__
        assert list(cx.globals) == ['foo']

def test_context_refcounts():
    called = []
    app = Flak(__name__)
    @app.teardown
    def teardown_app(cx, error=None):
        called.append('teardown app')
    @app.teardown
    def teardown_req(cx, error=None):
        called.append('teardown request')
    @app.route('/')
    def index(cx):
        env = cx.request.environ
        assert env['werkzeug.request'] is not None
        return u''
    c = app.test_client()
    res = c.get('/')
    assert res.status_code == 200
    assert res.data == b''
    assert called == ['teardown request', 'teardown app']



def test_teardown_on_pop():
    capture = []
    app = flak.Flak(__name__)
    @app.teardown
    def end_of_request(cx, exception):
        capture.append(exception)

    cx = app.test_context()
    assert capture == []
    cx.close()
    assert capture == [None]


def test_teardown_with_previous_exception():
    capture = []
    app = flak.Flak(__name__)
    @app.teardown
    def end_of_request(cx, exception):
        capture.append(exception)

    try:
        raise Exception('dummy')
    except Exception:
        pass

    with app.test_context():
        assert capture == []
    assert capture == [None]


def test_teardown_with_handled_exception():
    capture = []
    app = flak.Flak(__name__)
    @app.teardown
    def end_of_request(cx, exception):
        capture.append(exception)

    with app.test_context():
        assert capture == []
        try:
            raise Exception('dummy')
        except Exception:
            pass
    assert capture == [None]


def test_proper_test_context():
    app = flak.Flak(__name__)
    app.config.update(SERVER_NAME='localhost.localdomain:5000')

    @app.route('/')
    def index(cx):
        return None

    @app.route('/', subdomain='foo')
    def sub(cx):
        return None

    with app.test_context() as cx:
        assert cx.url_for('index', _external=True) == \
            'http://localhost.localdomain:5000/'

    with app.test_context() as cx:
        assert cx.url_for('sub', _external=True) == \
            'http://foo.localhost.localdomain:5000/'

    try:
        with app.test_context(environ_overrides={'HTTP_HOST': 'localhost'}):
            pass
    except ValueError as e:
        assert str(e) == (
            "the server name provided "
            "('localhost.localdomain:5000') does not match the "
            "server name from the WSGI environment ('localhost')"
        )

    app.config.update(SERVER_NAME='localhost')
    with app.test_context(environ_overrides={'SERVER_NAME': 'localhost'}):
        pass

    app.config.update(SERVER_NAME='localhost:80')
    with app.test_context(environ_overrides={'SERVER_NAME': 'localhost:80'}):
        pass


def test_context_binding():
    app = flak.Flak(__name__)
    @app.route('/')
    def index(cx):
        return 'Hello %s!' % cx.request.args['name']
    @app.route('/meh')
    def meh(cx):
        return cx.request.url

    with app.test_context('/?name=World') as cx:
        assert index(cx) == 'Hello World!'
    with app.test_context('/meh') as cx:
        assert meh(cx) == 'http://localhost/meh'


def test_manual_context_binding():
    app = flak.Flak(__name__)
    @app.route('/')
    def index(cx):
        return 'Hello %s!' % cx.request.args['name']

    cx = app.test_context('/?name=World')
    assert index(cx) == 'Hello World!'
    cx.close()

