# -*- coding: utf-8 -*-

from werkzeug.wrappers import Request as BaseRequest, Response as BaseResponse
from werkzeug.exceptions import BadRequest

from . import json

_sentinel = object()


def _get_data(req, cache):
    getter = getattr(req, 'get_data', None)
    if getter is not None:
        return getter(cache=cache)
    return req.data


class Request(BaseRequest):
    url_rule = None
    view_args = None
    routing_exception = None

    @property
    def endpoint(self):
        return self.url_rule and self.url_rule.endpoint

    @property
    def is_json(self):
        mt = self.mimetype
        if mt == 'application/json':
            return True
        if mt.startswith('application/') and mt.endswith('+json'):
            return True
        return False

    def _get_json(self, cx, force=False, silent=False, cache=True):
        rv = getattr(self, '_cached_json', _sentinel)
        if rv is not _sentinel:
            return rv

        if not (force or self.is_json):
            return None

        charset = self.mimetype_params.get('charset')
        try:
            data = _get_data(self, cache)
            if charset is not None:
                rv = cx.loads(data, encoding=charset)
            else:
                rv = cx.loads(data)
        except ValueError as e:
            if silent:
                rv = None
            else:
                rv = self.on_json_error(e)
        if cache:
            self._cached_json = rv
        return rv

    def on_json_error(self, e):
        if self.debug:
            raise BadRequest('Failed to decode JSON object: {0}'.format(e))
        raise BadRequest()

    def _load_form_data(self):
        BaseRequest._load_form_data(self)
        if (self.debug
                and self.mimetype != 'multipart/form-data'
                and not self.files):
            from .debughelpers import attach_enctype_error_multidict
            attach_enctype_error_multidict(self)

class Response(BaseResponse):
    default_mimetype = 'text/plain'

