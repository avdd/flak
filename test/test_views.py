# -*- coding: utf-8 -*-

import pytest
from flak import Flak, views
from flak.wrappers import Response
from werkzeug.http import parse_set_header


def common_asserts(app):
    c = app.test_client()
    assert c.get('/').data == b'GET'
    assert c.post('/').data == b'POST'
    assert c.put('/').status_code == 405
    meths = parse_set_header(c.open('/', method='OPTIONS').headers['Allow'])
    assert sorted(meths) == ['GET', 'HEAD', 'OPTIONS', 'POST']


def test_basic_view():
    app = Flak(__name__)

    class Index(views.View):
        methods = ['GET', 'POST']
        def dispatch_request(self, cx):
            return cx.request.method

    app.add_url_rule('/', Index.as_view('index'))
    common_asserts(app)

def test_method_based_view():
    app = Flak(__name__)

    class Index(views.MethodView):
        def get(self, cx):
            return 'GET'
        def post(self, cx):
            return 'POST'

    app.add_url_rule('/', Index.as_view('index'))
    common_asserts(app)

def test_view_patching():
    app = Flak(__name__)

    class Index(views.MethodView):
        def get(self, cx):
            1 // 0
        def post(self, cx):
            1 // 0

    class Other(Index):
        def get(self, cx):
            return 'GET'
        def post(self, cx):
            return 'POST'

    view = Index.as_view('index')
    view.view_class = Other
    app.add_url_rule('/', view)
    common_asserts(app)

def test_endpoint_override():
    app = Flak(__name__)
    app.debug = True

    class Index(views.View):
        methods = ['GET', 'POST']
        def dispatch_request(self, cx):
            return cx.request.method

    app.add_url_rule('/', Index.as_view('index'))

    with pytest.raises(AssertionError):
        app.add_url_rule('/', Index.as_view('index'))

    # But these tests should still pass. We just log a warning.
    common_asserts(app)

def test_explicit_head():
    app = Flak(__name__)

    class Index(views.MethodView):
        def get(self, cx):
            return 'GET'
        def head(self, cx):
            return Response('', headers={'X-Method': 'HEAD'})

    app.add_url_rule('/', Index.as_view('index'))
    c = app.test_client()
    rv = c.get('/')
    assert rv.data == b'GET'
    rv = c.head('/')
    assert rv.data == b''
    assert rv.headers['X-Method'] == 'HEAD'

def test_view_inheritance():
    app = Flak(__name__)

    class Index(views.MethodView):
        def get(self, cx):
            return 'GET'
        def post(self, cx):
            return 'POST'

    class BetterIndex(Index):
        def delete(self, cx):
            return 'DELETE'

    app.add_url_rule('/', BetterIndex.as_view('index'))
    c = app.test_client()

    meths = parse_set_header(c.open('/', method='OPTIONS').headers['Allow'])
    assert sorted(meths) == ['DELETE', 'GET', 'HEAD', 'OPTIONS', 'POST']

def test_view_decorators():
    app = Flak(__name__)

    def add_x_parachute(f):
        def new_function(cx, *args, **kwargs):
            resp = cx.make_response(f(cx, *args, **kwargs))
            resp.headers['X-Parachute'] = 'awesome'
            return resp
        return new_function

    class Index(views.View):
        decorators = [add_x_parachute]
        def dispatch_request(self, cx):
            return 'Awesome'

    app.add_url_rule('/', Index.as_view('index'))
    c = app.test_client()
    rv = c.get('/')
    assert rv.headers['X-Parachute'] == 'awesome'
    assert rv.data == b'Awesome'

def test_implicit_head():
    app = Flak(__name__)

    class Index(views.MethodView):
        def get(self, cx):
            headers={'X-Method': cx.request.method}
            return Response('Blub', headers=headers)

    app.add_url_rule('/', Index.as_view('index'))
    c = app.test_client()
    rv = c.get('/')
    assert rv.data == b'Blub'
    assert rv.headers['X-Method'] == 'GET'
    rv = c.head('/')
    assert rv.data == b''
    assert rv.headers['X-Method'] == 'HEAD'

