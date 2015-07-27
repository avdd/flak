# -*- coding: utf-8 -*-
import pytest
import flak
from flak._compat import text_type
from flak import Flak


def test_environ_defaults_from_config():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'example.com:1234'
    app.config['APPLICATION_ROOT'] = '/foo'
    @app.route('/')
    def index(cx):
        return cx.request.url

    cx = app.test_context()
    assert cx.request.url == 'http://example.com:1234/foo/'
    with app.test_client() as c:
        rv = c.get('/')
        assert rv.data == b'http://example.com:1234/foo/'

def test_environ_defaults():
    app = Flak(__name__)
    @app.route('/')
    def index(cx):
        return cx.request.url

    cx = app.test_context()
    assert cx.request.url == 'http://localhost/'
    with app.test_client() as c:
        rv = c.get('/')
        assert rv.data == b'http://localhost/'

def test_redirect_keep_session():
    app = Flak(__name__)
    app.secret_key = 'testing'

    @app.route('/', methods=['GET', 'POST'])
    def index(cx):
        if cx.request.method == 'POST':
            return flak.redirect('/getsession')
        cx.session['data'] = 'foo'
        return 'index'

    @app.route('/getsession')
    def get_session(cx):
        return cx.session.get('data', '<missing>')

    with app.test_client() as c:
        rv = c.get('/getsession')
        assert rv.data == b'<missing>'

        rv = c.get('/')
        assert rv.data == b'index'
        rv = c.post('/', data={}, follow_redirects=True)
        assert rv.data == b'foo'
        rv = c.get('/getsession')
        assert rv.data == b'foo'

def test_session_transactions():
    app = Flak(__name__)
    app.secret_key = 'testing'

    @app.route('/')
    def index(cx):
        return text_type(cx.session['foo'])

    with app.test_client() as c:
        with c.session() as sess:
            assert len(sess) == 0
            sess['foo'] = [42]
            assert len(sess) == 1
        rv = c.get('/')
        assert rv.data == b'[42]'
        with c.session() as sess:
            assert len(sess) == 1
            assert sess['foo'] == [42]

def test_session_transactions_keep_context():
    app = Flak(__name__)
    app.secret_key = 'testing'

    with app.test_client() as c:
        rv = c.get('/')
        cx = c.captured_context
        req = cx.request
        assert req is not None
        with c.session():
            assert req is cx.request

def test_session_transaction_needs_cookies():
    app = Flak(__name__)
    c = app.test_client(use_cookies=False)
    try:
        with c.session() as s:
            pass
    except RuntimeError as e:
        assert 'cookies' in str(e)
    else:
        assert False, 'Expected runtime error'

def test_test_client_context_binding():
    app = Flak(__name__)
    app.config['LOGGER_HANDLER_POLICY'] = 'never'
    @app.route('/')
    def index(cx):
        cx.globals.value = 42
        return 'Hello World!'

    @app.route('/other')
    def other(cx):
        cx.globals.value = 23
        1 // 0

    with app.test_client() as c:
        resp = c.get('/')
        cx = c.captured_context
        assert cx.globals.value == 42
        assert resp.data == b'Hello World!'
        assert resp.status_code == 200

        resp = c.get('/other')
        assert b'Internal Server Error' in resp.data
        assert resp.status_code == 500
        assert c.captured_context is not cx
        cx = c.captured_context
        assert cx.globals.value == 23

def test_reuse_client():
    app = Flak(__name__)
    c = app.test_client()
    with c:
        assert c.get('/').status_code == 404
    with c:
        assert c.get('/').status_code == 404

def test_test_client_calls_teardown_handlers():
    app = Flak(__name__)
    called = []
    @app.teardown
    def remember(cx, error):
        called.append(error)

    with app.test_client() as c:
        assert called == []
        c.get('/')
        #assert called == []
        assert called == [None]
    assert called == [None]

    del called[:]
    with app.test_client() as c:
        assert called == []
        c.get('/')
        #assert called == []
        assert called == [None]
        c.get('/')
        #assert called == [None]
        assert called == [None, None]
    assert called == [None, None]

def test_full_url_request():
    app = Flak(__name__)

    @app.route('/action', methods=['POST'])
    def action(cx):
        return 'x'

    with app.test_client() as c:
        rv = c.post('http://domain.com/action?vodka=42', data={'gin': 43})
        cx = c.captured_context
        assert rv.status_code == 200
        assert 'gin' in cx.request.form
        assert 'vodka' in cx.request.args

def test_subdomain():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'example.com'
    @app.route('/', subdomain='<company_id>')
    def view(cx, company_id):
        return company_id

    with app.test_context() as cx:
        url = cx.url_for('view', company_id='xxx')

    with app.test_client() as c:
        response = c.get(url)

    assert 200 == response.status_code
    assert b'xxx' == response.data

def test_nosubdomain():
    app = Flak(__name__)
    app.config['SERVER_NAME'] = 'example.com'
    @app.route('/<company_id>')
    def view(cx, company_id):
        return company_id

    with app.test_context() as cx:
        url = cx.url_for('view', company_id='xxx')

    with app.test_client() as c:
        response = c.get(url)

    assert 200 == response.status_code
    assert b'xxx' == response.data

