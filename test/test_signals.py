# -*- coding: utf-8 -*-
import pytest
import flak

try:
    import blinker
except ImportError:
    blinker = None


pytestmark = pytest.mark.skipif(
    blinker is None,
    reason='Signals require the blinker library.'
)

def test_request_signals():
    app = flak.Flak(__name__)
    calls = []

    def before_request_signal(app, context):
        calls.append('before-signal')

    def after_request_signal(app, context, response):
        assert response.data == b'stuff'
        calls.append('after-signal')

    @app.before_request
    def before_request_handler(cx):
        calls.append('before-handler')

    @app.after_request
    def after_request_handler(cx, response):
        calls.append('after-handler')
        response.data = 'stuff'
        return response

    @app.route('/')
    def index(cx):
        calls.append('handler')
        return 'ignored anyway'

    flak.request_started.connect(before_request_signal, app)
    flak.request_finished.connect(after_request_signal, app)

    try:
        rv = app.test_client().get()
        assert rv.data == b'stuff'

        assert calls == ['before-signal', 'before-handler', 'handler',
                         'after-handler', 'after-signal']
    finally:
        flak.request_started.disconnect(before_request_signal, app)
        flak.request_finished.disconnect(after_request_signal, app)

def test_request_exception_signal():
    app = flak.Flak(__name__)
    recorded = []

    @app.route('/')
    def index(cx):
        1 // 0

    def record(sender, context, exception):
        recorded.append(exception)

    flak.request_exception.connect(record, app)
    try:
        assert app.test_client().get().status_code == 500
        assert len(recorded) == 1
        assert isinstance(recorded[0], ZeroDivisionError)
    finally:
        flak.request_exception.disconnect(record, app)

def test_context_signals():
    app = flak.Flak(__name__)
    recorded = []

    def record_push(sender, **kw):
        recorded.append('push')

    def record_pop(sender, **kw):
        recorded.append('pop')

    @app.route('/')
    def index(cx):
        return 'Hello'

    flak.context_created.connect(record_push, app)
    flak.context_teardown.connect(record_pop, app)
    try:
        c = app.test_client()
        rv = c.get()
        assert recorded == ['push', 'pop']
        assert recorded == ['push', 'pop']
    finally:
        flak.context_created.disconnect(record_push, app)
        flak.context_teardown.disconnect(record_pop, app)

def test_teardown_signals():
    app = flak.Flak(__name__)
    recorded = []

    def record_teardown(sender, **kw):
        #recorded.append(('tear_down', kw))
        recorded.append(('tear_down', set(kw.keys())))

    @app.route('/')
    def index(cx):
        1 // 0

    flak.context_teardown.connect(record_teardown, app)
    try:
        c = app.test_client()
        rv = c.get()
        assert rv.status_code == 500
        assert recorded == [('tear_down', set(['context', 'exception']))]
        #assert recorded == [('tear_down', {'exc': None})]
    finally:
        flak.context_teardown.disconnect(record_teardown, app)

