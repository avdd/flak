# -*- coding: utf-8 -*-

import sys
from werkzeug.exceptions import HTTPException
from .helpers import _url_for
from flak import json

_sentinel = object()


class Bucket(object):
    def get(self, name, default=None):
        return self.__dict__.get(name, default)
    def pop(self, name, default=_sentinel):
        if default is _sentinel:
            return self.__dict__.pop(name)
        else:
            return self.__dict__.pop(name, default)
    def setdefault(self, name, default=None):
        self.__dict__.setdefault(name, default)
    def __contains__(self, item):
        return item in self.__dict__
    def __iter__(self):
        return iter(self.__dict__)
    def __repr__(self):
        return '<flak.global>'


class AppContext(object):
    request = None
    def __init__(self, app):
        self.app = app
        self.globals = app.context_globals_class()
        self._before_close_funcs = []
        if 0 and hasattr(sys, 'exc_clear'):
            sys.exc_clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.close(exc_value)

    def close(self, exc=_sentinel):
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        for f in self._before_close_funcs:
            f(exc)
        self.app.do_teardown(self, exc)
        if hasattr(sys, 'exc_clear'):
            sys.exc_clear()

    @property
    def before_close(self):
        def decorator(f):
            self._before_close_funcs.append(f)
        return decorator

    @property
    def url_adapter(self):
        return self.app.create_url_adapter(self)

    def dumps(__self, *__args, **__kw):
        json.dump_defaults(__self.app, __kw)
        return json._dumps(*__args, **__kw)

    def dump(__self, *__args, **__kw):
        json.dump_defaults(__self.app, __kw)
        return json._dump(*__args, **__kw)

    def loads(__self, *__args, **__kw):
        json.load_defaults(__self.app, __kw)
        return json._loads(*__args, **__kw)

    def load(__self, *__args, **__kw):
        json.load_defaults(__self.app, __kw)
        return json._load(*__args, **__kw)

    def url_for(__self, __x, **__values):
        return _url_for(__self, __x, __values)


class RequestContext(AppContext):

    def __init__(self, app, rq):
        self.request = rq
        AppContext.__init__(self, app)
        self.match_request()
        self.session = self.app.open_session(self)
        self._after_request_funcs = []
        assert self.session is not None

    def __repr__(self):
        f = '<%s \'%s\' [%s] of %s>'
        return f % (self.__class__.__name__,
                    self.request.url,
                    self.request.method,
                    self.app.name)

    @property
    def after_request(self):
        def decorator(f):
            self._after_request_funcs.append(f)
        return decorator

    def process_response(self, response):
        for f in self._after_request_funcs:
            response = f(response)
        return response

    def copy(self):
        return self.__class__(self.app, self.request)

    def match_request(self):
        adapter = self.url_adapter
        rq = self.request
        try:
            rq.url_rule, rq.view_args = adapter.match(return_rule=True)
        except HTTPException as e:
            self.request.routing_exception = e

    def close(self, exc=_sentinel):
        AppContext.close(self, exc)
        request_close = getattr(self.request, 'close', None)
        if request_close is not None:
            request_close()
        # clean up circular dependencies
        self.request.environ['werkzeug.request'] = None

    def jsonify(__self, *args, **kw):
        return json.jsonify(__self, *args, **kw)

    def make_response(self, *args):
        if not args:
            return self.app.response_class()
        if len(args) == 1:
            args = args[0]
        return self.app.make_response(self, args)

    def get_json(self, *args, **kw):
        return self.request._get_json(self, *args, **kw)

    def streaming(self, f):
        def call(*args, **kw):
            return self.close_with_generator(f(*args, **kw))
        return call

    def close_with_generator(self, generator):
        gen = iter(generator)
        close = self.close
        def ignore(_): pass
        self.close = ignore
        return closer(gen, close)


def closer(gen, close):
    error = None
    try:
        for x in gen:
            yield x
    except Exception as e:
        error = e
    finally:
        if hasattr(gen, 'close'):
            gen.close()
        close(error)


