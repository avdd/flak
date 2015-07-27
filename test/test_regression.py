# -*- coding: utf-8 -*-
import pytest
import flak
from werkzeug.exceptions import NotFound


def test_aborting():
    class Foo(Exception):
        whatever = 42
    app = flak.Flak(__name__)

    @app.errorhandler(Foo)
    def handle_foo(cx, e):
        return str(e.whatever)

    @app.route('/')
    def index(cx):
        raise flak.abort(flak.redirect(cx.url_for('test')))

    @app.route('/test')
    def test(cx):
        raise Foo()

    with app.test_client() as c:
        rv = c.get('/')
        assert rv.headers['Location'] == 'http://localhost/test'
        rv = c.get('/test')
        assert rv.data == b'42'

