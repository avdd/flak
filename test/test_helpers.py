# -*- coding: utf-8 -*-
import pytest
import os
import datetime
import flak
from logging import StreamHandler
from werkzeug.http import parse_cache_control_header, parse_options_header
from werkzeug.http import http_date
from itsdangerous import json
from flak._compat import StringIO, text_type
from flak import Flak


def has_encoding(name):
    try:
        import codecs
        codecs.lookup(name)
        return True
    except LookupError:
        return False


class TestJSON(object):

    def test_jsonify_date_types(self):
        test_dates = (datetime.datetime(1973, 3, 11, 6, 30, 45),
                      datetime.date(1975, 1, 5))

        app = Flak(__name__)
        c = app.test_client()

        for i, d in enumerate(test_dates):
            url = '/datetest{0}'.format(i)
            f = lambda cx, val=d: cx.jsonify(x=val)
            app.add_url_rule(url, f, str(i))
            rv = c.get(url)
            assert rv.mimetype == 'application/json'
            assert json.loads(rv.data)['x'] == http_date(d.timetuple())

    def test_post_empty_json_adds_exception_to_response_content_in_debug(self):
        app = Flak(__name__)
        app.config['DEBUG'] = True
        @app.route('/json', methods=['POST'])
        def post_json(cx):
            cx.get_json()
            return None
        c = app.test_client()
        rv = c.post('/json', data=None, content_type='application/json')
        assert rv.status_code == 400
        assert b'Failed to decode JSON object' in rv.data

    def test_post_empty_json_wont_add_exception_to_response_if_no_debug(self):
        app = Flak(__name__)
        app.config['DEBUG'] = False
        @app.route('/json', methods=['POST'])
        def post_json(cx):
            cx.get_json()
            return None
        c = app.test_client()
        rv = c.post('/json', data=None, content_type='application/json')
        assert rv.status_code == 400
        assert b'Failed to decode JSON object' not in rv.data

    def test_json_bad_requests(self):
        app = Flak(__name__)
        @app.route('/json', methods=['POST'])
        def return_json(cx):
            return cx.jsonify(foo=text_type(cx.get_json()))
        c = app.test_client()
        rv = c.post('/json', data='malformed', content_type='application/json')
        assert rv.status_code == 400

    def test_json_custom_mimetypes(self):
        app = Flak(__name__)
        @app.route('/json', methods=['POST'])
        def return_json(cx):
            return cx.get_json()
        c = app.test_client()
        rv = c.post('/json', data='"foo"', content_type='application/x+json')
        assert rv.data == b'foo'

    def test_json_body_encoding(self):
        app = Flak(__name__)
        @app.route('/')
        def index(cx):
            return cx.get_json()

        c = app.test_client()
        resp = c.get('/', data=u'"Hällo Wörld"'.encode('iso-8859-15'),
                     content_type='application/json; charset=iso-8859-15')
        assert resp.data == u'Hällo Wörld'.encode('utf-8')

    def test_jsonify(self):
        d = dict(a=23, b=42, c=[1, 2, 3])
        app = Flak(__name__)
        @app.route('/kw')
        def return_kwargs(cx):
            return cx.jsonify(**d)
        @app.route('/dict')
        def return_dict(cx):
            return cx.jsonify(d)
        c = app.test_client()
        for url in '/kw', '/dict':
            rv = c.get(url)
            assert rv.mimetype == 'application/json'
            assert json.loads(rv.data) == d

    def test_json_as_unicode(self):
        app = Flak(__name__)

        app.config['JSON_AS_ASCII'] = True
        with app.new_context() as cx:
            rv = cx.dumps(u'\N{SNOWMAN}')
            assert rv == '"\\u2603"'

        app.config['JSON_AS_ASCII'] = False
        with app.new_context() as cx:
            rv = cx.dumps(u'\N{SNOWMAN}')
            assert rv == u'"\u2603"'

    def test_json_attr(self):
        app = Flak(__name__)
        @app.route('/add', methods=['POST'])
        def add(cx):
            json = cx.get_json()
            return text_type(json['a'] + json['b'])
        c = app.test_client()
        rv = c.post('/add', data=json.dumps({'a': 1, 'b': 2}),
                            content_type='application/json')
        assert rv.data == b'3'

    def test_json_customization(self):
        class X(object):
            def __init__(self, val):
                self.val = val
        class MyEncoder(flak.json.JSONEncoder):
            def default(self, o):
                if isinstance(o, X):
                    return '<%d>' % o.val
                return flak.json.JSONEncoder.default(self, o)
        class MyDecoder(flak.json.JSONDecoder):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault('object_hook', self.object_hook)
                flak.json.JSONDecoder.__init__(self, *args, **kwargs)
            def object_hook(self, obj):
                if len(obj) == 1 and '_foo' in obj:
                    return X(obj['_foo'])
                return obj
        app = Flak(__name__)
        app.json_encoder = MyEncoder
        app.json_decoder = MyDecoder
        @app.route('/', methods=['POST'])
        def index(cx):
            return cx.dumps(cx.get_json()['x'])
        c = app.test_client()
        rv = c.post('/', data=json.dumps({
            'x': {'_foo': 42}
        }), content_type='application/json')
        assert rv.data == b'"<42>"'

    def test_modified_url_encoding(self):
        class ModifiedRequest(flak.Request):
            url_charset = 'euc-kr'
        app = Flak(__name__)
        app.request_class = ModifiedRequest
        app.url_map.charset = 'euc-kr'

        @app.route('/')
        def index(cx):
            return cx.request.args['foo']

        rv = app.test_client().get(u'/?foo=정상처리'.encode('euc-kr'))
        assert rv.status_code == 200
        assert rv.data == u'정상처리'.encode('utf-8')

    if not has_encoding('euc-kr'):
        test_modified_url_encoding = None

    def test_json_key_sorting(self):
        app = Flak(__name__)
        assert app.config['JSON_SORT_KEYS'] == True
        d = dict.fromkeys(range(20), 'foo')

        @app.route('/')
        def index(cx):
            return cx.jsonify(values=d)

        c = app.test_client()
        rv = c.get('/')
        lines = [x.strip() for x in rv.data.strip().decode('utf-8').splitlines()]
        sorted_by_str = [
            '{',
            '"values": {',
            '"0": "foo",',
            '"1": "foo",',
            '"10": "foo",',
            '"11": "foo",',
            '"12": "foo",',
            '"13": "foo",',
            '"14": "foo",',
            '"15": "foo",',
            '"16": "foo",',
            '"17": "foo",',
            '"18": "foo",',
            '"19": "foo",',
            '"2": "foo",',
            '"3": "foo",',
            '"4": "foo",',
            '"5": "foo",',
            '"6": "foo",',
            '"7": "foo",',
            '"8": "foo",',
            '"9": "foo"',
            '}',
            '}'
        ]
        sorted_by_int = [
            '{',
            '"values": {',
            '"0": "foo",',
            '"1": "foo",',
            '"2": "foo",',
            '"3": "foo",',
            '"4": "foo",',
            '"5": "foo",',
            '"6": "foo",',
            '"7": "foo",',
            '"8": "foo",',
            '"9": "foo",',
            '"10": "foo",',
            '"11": "foo",',
            '"12": "foo",',
            '"13": "foo",',
            '"14": "foo",',
            '"15": "foo",',
            '"16": "foo",',
            '"17": "foo",',
            '"18": "foo",',
            '"19": "foo"',
            '}',
            '}'
        ]

        try:
            assert lines == sorted_by_int
        except AssertionError:
            assert lines == sorted_by_str

class TestLogging(object):

    def test_logger_cache(self):
        app = Flak(__name__)
        logger1 = app.logger
        assert app.logger is logger1
        assert logger1.name == __name__
        app.logger_name = __name__ + '/test_logger_cache'
        assert app.logger is not logger1

    def test_debug_log(self, capsys):
        app = Flak(__name__)
        app.debug = True

        @app.route('/')
        def index(cx):
            app.logger.warning('the standard library is dead')
            app.logger.debug('this is a debug statement')
            return ''

        @app.route('/exc')
        def exc(cx):
            1 // 0

        with app.test_client() as c:
            c.get('/')
            out, err = capsys.readouterr()
            assert 'WARNING in test_helpers [' in err
            assert os.path.basename(__file__.rsplit('.', 1)[0] + '.py') in err
            assert 'the standard library is dead' in err
            assert 'this is a debug statement' in err

            with pytest.raises(ZeroDivisionError):
                c.get('/exc')

    def test_debug_log_override(self):
        app = Flak(__name__)
        app.debug = True
        app.logger_name = 'flak_tests/test_debug_log_override'
        app.logger.level = 10
        assert app.logger.level == 10

    def test_exception_logging(self):
        out = StringIO()
        app = Flak(__name__)
        app.config['LOGGER_HANDLER_POLICY'] = 'never'
        app.logger_name = 'flak_tests/test_exception_logging'
        app.logger.addHandler(StreamHandler(out))

        @app.route('/')
        def index(cx):
            1 // 0

        rv = app.test_client().get('/')
        assert rv.status_code == 500
        assert b'Internal Server Error' in rv.data

        err = out.getvalue()
        assert 'Exception on / [GET]' in err
        assert 'Traceback (most recent call last):' in err
        assert '1 // 0' in err
        assert 'ZeroDivisionError:' in err

    def test_processor_exceptions(self):
        app = Flak(__name__)
        app.config['LOGGER_HANDLER_POLICY'] = 'never'
        @app.before_request
        def before_request():
            if trigger == 'before':
                1 // 0
        @app.after_request
        def after_request(response):
            if trigger == 'after':
                1 // 0
            return response
        @app.route('/')
        def index():
            return 'Foo'
        @app.errorhandler(500)
        def internal_server_error(cx, e):
            return 'Hello Server Error', 500
        for trigger in 'before', 'after':
            rv = app.test_client().get('/')
            assert rv.status_code == 500
            assert rv.data == b'Hello Server Error'

    def test_url_for_with_anchor(self):
        app = Flak(__name__)
        @app.route('/')
        def index():
            return '42'
        with app.test_context() as cx:
            assert cx.url_for('index', _anchor='x y') == '/#x%20y'

    def test_url_for_with_scheme(self):
        app = Flak(__name__)
        @app.route('/')
        def index():
            return '42'
        with app.test_context() as cx:
            assert cx.url_for('index', _external=True, _scheme='https') == 'https://localhost/'

    def test_url_for_with_scheme_not_external(self):
        app = Flak(__name__)
        @app.route('/')
        def index():
            return '42'
        with app.test_context() as cx:
            pytest.raises(ValueError,
                               cx.url_for,
                               'index',
                               _scheme='https')

    def test_url_with_method(self):
        from flak.views import MethodView
        app = Flak(__name__)
        class MyView(MethodView):
            def get(self, id=None):
                if id is None:
                    return 'List'
                return 'Get %d' % id
            def post(self):
                return 'Create'
        myview = MyView.as_view('myview')
        app.add_url_rule('/myview/', myview, methods=['GET'])
        app.add_url_rule('/myview/<int:id>', myview, methods=['GET'])
        app.add_url_rule('/myview/create', myview, methods=['POST'])

        with app.test_context() as cx:
            assert cx.url_for('myview', _method='GET') == '/myview/'
            assert cx.url_for('myview', id=42, _method='GET') == '/myview/42'
            assert cx.url_for('myview', _method='POST') == '/myview/create'


class TestNoImports(object):
    """Test Flaks are created without import.

    Avoiding ``__import__`` helps create Flak instances where there are errors
    at import time.  Those runtime errors will be apparent to the user soon
    enough, but tools which build Flak instances meta-programmatically benefit
    from a Flak which does not ``__import__``.  Instead of importing to
    retrieve file paths or metadata on a module or package, use the pkgutil and
    imp modules in the Python standard library.
    """

    def test_name_with_import_error(self, modules_tmpdir):
        modules_tmpdir.join('importerror.py').write('raise NotImplementedError()')
        try:
            Flak('importerror')
        except NotImplementedError:
            assert False, 'Flak(import_name) is importing import_name.'


class TestStreaming(object):

    def test_streaming_with_context(self):
        app = Flak(__name__)
        @app.route('/')
        def index(cx):
            def generate():
                yield 'Hello '
                yield cx.request.args['name']
                yield '!'
            gen = cx.close_with_generator(generate())
            return flak.Response(gen)
        c = app.test_client()
        rv = c.get('/?name=World')
        assert rv.data == b'Hello World!'

    def test_streaming_as_decorator(self):
        app = Flak(__name__)
        @app.route('/')
        def index(cx):
            @cx.streaming
            def generate():
                yield 'Hello '
                yield cx.request.args['name']
                yield '!'
            return flak.Response(generate())
        c = app.test_client()
        rv = c.get('/?name=World')
        assert rv.data == b'Hello World!'

    def test_streaming_with_context_and_custom_close(self):
        app = Flak(__name__)
        called = []
        class Wrapper(object):
            def __init__(self, gen):
                self._gen = gen
            def __iter__(self):
                return self
            def close(self):
                called.append(42)
            def __next__(self):
                return next(self._gen)
            next = __next__
        @app.route('/')
        def index(cx):
            def generate():
                yield 'Hello '
                yield cx.request.args['name']
                yield '!'
            gen = cx.close_with_generator(Wrapper(generate()))
            return flak.Response(gen)
        c = app.test_client()
        rv = c.get('/?name=World')
        assert rv.data == b'Hello World!'
        assert called == [42]

    def test_streaming_context_closes_on_stopiter(self):
        app = Flak(__name__)
        called = []
        class Wrapper(object):
            def __init__(self, gen):
                self._gen = gen
            def __iter__(self):
                return self
            def close(self):
                assert not called
                called.append('gen.close')
            def __next__(self):
                return next(self._gen)
            next = __next__

        @app.route('/')
        def index(cx):
            @cx.after_request
            def onfinish(rsp):
                assert not called

            @cx.before_close
            def onclose(exc):
                called.append('cx.close')

            def generate():
                yield '1'
                yield '2'
                yield '3'
                assert not called

            gen = cx.close_with_generator(Wrapper(generate()))
            return flak.Response(gen)

        rv = app.test_client().get('/')
        assert rv.data == b'123'
        assert called == ['gen.close', 'cx.close']

