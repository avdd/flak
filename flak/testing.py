# -*- coding: utf-8 -*-

from contextlib import contextmanager
from werkzeug.test import Client, EnvironBuilder
from werkzeug.urls import url_parse

from .signals import context_created, context_teardown

def make_test_environ_builder(app, path='/', base_url=None, *args, **kwargs):
    http_host = app.config.get('SERVER_NAME')
    app_root = app.config.get('APPLICATION_ROOT')
    if base_url is None:
        url = url_parse(path)
        base_url = 'http://%s/' % (url.netloc or http_host or 'localhost')
        if app_root:
            base_url += app_root.lstrip('/')
        if url.netloc:
            path = url.path
            if url.query:
                path += '?' + url.query
    return EnvironBuilder(path, base_url, *args, **kwargs)


class FlakClient(Client):

    def __enter__(self):
        context_created.connect(self.capture_context, self.application)
        return self

    def __exit__(self, exc_type, exc_value, tb):
        context_created.disconnect(self.capture_context, self.application)

    def capture_context(self, app, context):
        self.captured_context = context

    @contextmanager
    def session(self, *args, **kwargs):
        if self.cookie_jar is None:
            raise RuntimeError('Session transactions only make sense '
                               'with cookies enabled.')
        app = self.application
        environ_overrides = kwargs.setdefault('environ_overrides', {})
        self.cookie_jar.inject_wsgi(environ_overrides)
        with app.test_context(*args, **kwargs) as cx:
            sess = cx.session
            yield sess
            resp = app.response_class()
            app.save_session(cx, resp)
            headers = resp.get_wsgi_headers(cx.request.environ)
            self.cookie_jar.extract_wsgi(cx.request.environ, headers)

    def open(self, *args, **kwargs):
        env = kwargs.setdefault('environ_overrides', {})
        as_tuple = kwargs.pop('as_tuple', False)
        buffered = kwargs.pop('buffered', False)
        follow_redirects = kwargs.pop('follow_redirects', False)
        builder = make_test_environ_builder(self.application, *args, **kwargs)
        return Client.open(self, builder,
                           as_tuple=as_tuple,
                           buffered=buffered,
                           follow_redirects=follow_redirects)

