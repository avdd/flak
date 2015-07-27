# -*- coding: utf-8 -*-

import io
import uuid
import datetime
from werkzeug.http import http_date
from itsdangerous import json as _json
from ._compat import text_type, PY2


class JSONEncoder(_json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.date):
            return http_date(o.timetuple())
        if isinstance(o, uuid.UUID):
            return str(o)
        if hasattr(o, '__html__'):
            return text_type(o.__html__())
        return _json.JSONEncoder.default(self, o)


class JSONDecoder(_json.JSONDecoder):
    pass


def jsonify(__cx, *__args, **__kw):
    app = __cx.app
    rq = __cx.request
    pretty = (app.config['JSONIFY_PRETTYPRINT_REGULAR']
              and not rq.is_xhr)
    # For security reasons only objects are supported toplevel
    indent = None
    separators = (',', ':')
    if pretty:
        indent = 2
        separators = (', ', ': ')
    json = __cx.dumps(dict(*__args, **__kw),
                      indent=indent,
                      separators=separators)
    # add '\n' to end of response
    # see https://github.com/mitsuhiko/flak/pull/1262
    return app.response_class((json, '\n'),
                              mimetype='application/json')

def dump_defaults(app, kw):
    if app:
        kw.setdefault('cls', app.json_encoder)
        if not app.config['JSON_AS_ASCII']:
            kw.setdefault('ensure_ascii', False)
        kw.setdefault('sort_keys', app.config['JSON_SORT_KEYS'])
    else:
        kw.setdefault('sort_keys', True)
        kw.setdefault('cls', JSONEncoder)

def load_defaults(app, kw):
    if app:
        kw.setdefault('cls', app.json_decoder)
    else:
        kw.setdefault('cls', JSONDecoder)

def _dumps(obj, **kw):
    encoding = kw.pop('encoding', None)
    rv = _json.dumps(obj, **kw)
    if encoding is not None and isinstance(rv, text_type):
        rv = rv.encode(encoding)
    return rv

def _dump(obj, fp, **kw):
    encoding = kw.pop('encoding', None)
    if encoding is not None:
        fp = _wrap_writer_for_text(fp, encoding)
    _json.dump(obj, fp, **kw)

def _loads(s, **kw):
    if isinstance(s, bytes):
        s = s.decode(kw.pop('encoding', None) or 'utf-8')
    return _json.loads(s, **kw)

def _load(fp, **kw):
    if not PY2:
        fp = _wrap_reader_for_text(fp, kw.pop('encoding', None) or 'utf-8')
    return _json.load(fp, **kw)

def _wrap_reader_for_text(fp, encoding):
    if isinstance(fp.read(0), bytes):
        fp = io.TextIOWrapper(io.BufferedReader(fp), encoding)
    return fp

def _wrap_writer_for_text(fp, encoding):
    try:
        fp.write('')
    except TypeError:
        fp = io.TextIOWrapper(fp, encoding)
    return fp

