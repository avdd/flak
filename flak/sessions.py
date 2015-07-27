# -*- coding: utf-8 -*-
import uuid
import hashlib
from base64 import b64encode, b64decode
from datetime import datetime
from werkzeug.http import http_date, parse_date
from werkzeug.datastructures import CallbackDict
from . import json
from ._compat import iteritems, text_type

from itsdangerous import URLSafeTimedSerializer, BadSignature


def total_seconds(td):
    return td.days * 60 * 60 * 24 + td.seconds


class SessionMixin(object):
    new = False
    modified = True

    def _get_permanent(self):
        return self.get('_permanent', False)

    def _set_permanent(self, value):
        self['_permanent'] = bool(value)

    permanent = property(_get_permanent, _set_permanent)
    del _get_permanent, _set_permanent


def _tag(value):
    if isinstance(value, tuple):
        return {' t': [_tag(x) for x in value]}
    elif isinstance(value, uuid.UUID):
        return {' u': value.hex}
    elif isinstance(value, bytes):
        return {' b': b64encode(value).decode('ascii')}
    elif callable(getattr(value, '__html__', None)):
        return {' m': text_type(value.__html__())}
    elif isinstance(value, list):
        return [_tag(x) for x in value]
    elif isinstance(value, datetime):
        return {' d': http_date(value)}
    elif isinstance(value, dict):
        return dict((k, _tag(v)) for k, v in iteritems(value))
    elif isinstance(value, str):
        try:
            return text_type(value)
        except UnicodeError:
            from flak.debughelpers import UnexpectedUnicodeError
            raise UnexpectedUnicodeError(u'A byte string with '
                u'non-ASCII data was passed to the session system '
                u'which can only store unicode strings.  Consider '
                u'base64 encoding your string (String was %r)' % value)
    return value


class TaggedJsonSerializer(object):

    def __init__(self, cx):
        self.cx = cx

    def dumps(self, value):
        return self.cx.dumps(_tag(value), separators=(',', ':'))

    def loads(self, value):
        def object_hook(obj):
            if len(obj) != 1:
                return obj
            the_key, the_value = next(iteritems(obj))
            if the_key == ' t':
                return tuple(the_value)
            elif the_key == ' u':
                return uuid.UUID(the_value)
            elif the_key == ' b':
                return b64decode(the_value)
            elif the_key == ' d':
                return parse_date(the_value)
            return obj
        return self.cx.loads(value, object_hook=object_hook)


class SecureCookieSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None):
        def on_update(self):
            self.modified = True
        CallbackDict.__init__(self, initial, on_update)
        self.modified = False


class NullSession(SecureCookieSession):
    modified = False
    def _nop(self, *args, **kwargs):
        pass
    __setitem__ = __delitem__ = clear = pop = popitem \
                = update = setdefault = _nop
    del _nop


class SessionInterface(object):
    null_session_class = NullSession

    def get_cookie_domain(self, app):
        if app.config['SESSION_COOKIE_DOMAIN'] is not None:
            return app.config['SESSION_COOKIE_DOMAIN']
        if app.config['SERVER_NAME'] is not None:
            # chop off the port which is usually not supported by browsers
            rv = '.' + app.config['SERVER_NAME'].rsplit(':', 1)[0]

            # Google chrome does not like cookies set to .localhost, so
            # we just go with no domain then.  Flak documents anyways that
            # cross domain cookies need a fully qualified domain name
            if rv == '.localhost':
                rv = None

            # If we infer the cookie domain from the server name we need
            # to check if we are in a subpath.  In that case we can't
            # set a cross domain cookie.
            if rv is not None:
                path = self.get_cookie_path(app)
                if path != '/':
                    rv = rv.lstrip('.')

            return rv

    def get_cookie_path(self, app):
        return (app.config['SESSION_COOKIE_PATH']
                or app.config['APPLICATION_ROOT']
                or '/')

    def get_cookie_httponly(self, app):
        return app.config['SESSION_COOKIE_HTTPONLY']

    def get_cookie_secure(self, app):
        return app.config['SESSION_COOKIE_SECURE']

    def get_expiration_time(self, app, session):
        if session.permanent:
            return datetime.utcnow() + app.permanent_session_lifetime

    def should_set_cookie(self, app, session):
        if session.modified:
            return True
        save_each = app.config['SESSION_REFRESH_EACH_REQUEST']
        return save_each and session.permanent

    def open_session(self, cx):
        return self.null_session_class()

    def save_session(self, cx, response):
        pass


class SecureCookieSessionInterface(SessionInterface):
    salt = 'cookie-session'
    key_derivation = 'hmac'
    digest_method = staticmethod(hashlib.sha1)
    serializer = TaggedJsonSerializer
    session_class = SecureCookieSession

    def get_signing_serializer(self, cx):
        if not cx.app.secret_key:
            return None
        signer_kwargs = dict(key_derivation=self.key_derivation,
                             digest_method=self.digest_method)
        return URLSafeTimedSerializer(cx.app.secret_key, salt=self.salt,
                                      serializer=self.serializer(cx),
                                      signer_kwargs=signer_kwargs)

    def open_session(self, cx):
        app = cx.app
        rq = cx.request
        s = self.get_signing_serializer(cx)
        if s is None:
            return self.null_session_class()
        val = rq.cookies.get(app.session_cookie_name)
        if not val:
            return self.session_class()
        max_age = total_seconds(app.permanent_session_lifetime)
        try:
            data = s.loads(val, max_age=max_age)
            return self.session_class(data)
        except BadSignature:
            return self.session_class()

    def save_session(self, cx, response):
        app = cx.app
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)

        # Delete case.  If there is no session we bail early.
        # If the session was modified to be empty we remove the
        # whole cookie.
        session = cx.session
        if not session:
            if session.modified:
                response.delete_cookie(app.session_cookie_name,
                                       domain=domain, path=path)
            return

        # Modification case.  There are upsides and downsides to
        # emitting a set-cookie header each request.  The behavior
        # is controlled by the :meth:`should_set_cookie` method
        # which performs a quick check to figure out if the cookie
        # should be set or not.  This is controlled by the
        # SESSION_REFRESH_EACH_REQUEST config flag as well as
        # the permanent flag on the session itself.
        if not self.should_set_cookie(app, session):
            return

        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(cx).dumps(dict(session))
        response.set_cookie(app.session_cookie_name, val,
                            expires=expires, httponly=httponly,
                            domain=domain, path=path, secure=secure)

