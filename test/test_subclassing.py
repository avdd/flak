# -*- coding: utf-8 -*-
import flak
from logging import StreamHandler
from flak._compat import StringIO


def test_suppressed_exception_logging():
    class SuppressedFlak(flak.Flak):
        def log_exception(self, cx, exc_info):
            pass

    out = StringIO()
    app = SuppressedFlak(__name__)
    app.logger_name = 'flaktest/test_suppressed_exception_logging'
    app.logger.addHandler(StreamHandler(out))

    @app.route('/')
    def index():
        1 // 0

    rv = app.test_client().get('/')
    assert rv.status_code == 500
    assert b'Internal Server Error' in rv.data

    err = out.getvalue()
    assert err == ''

