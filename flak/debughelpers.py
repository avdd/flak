# -*- coding: utf-8 -*-
from ._compat import implements_to_string, text_type


def attach_enctype_error_multidict(rq):
    oldcls = rq.files.__class__
    class newcls(oldcls):
        def __getitem__(self, key):
            try:
                return oldcls.__getitem__(self, key)
            except KeyError:
                if key not in rq.form:
                    raise
                raise DebugFilesKeyError(rq, key)
    newcls.__name__ = oldcls.__name__
    newcls.__module__ = oldcls.__module__
    rq.files.__class__ = newcls


class UnexpectedUnicodeError(AssertionError, UnicodeError):
    pass


@implements_to_string
class DebugFilesKeyError(KeyError, AssertionError):
    def __init__(self, rq, key):
        form_matches = rq.form.getlist(key)
        buf = ['Attempt to access the file "%s" in the request.files '
               'dictionary but it does not exist.  The mimetype for the request '
               'is "%s" instead of "multipart/form-data" which means that no '
               'file contents were transmitted.  To fix this error you should '
               'provide enctype="multipart/form-data" in your form.' %
               (key, rq.mimetype)]
        if form_matches:
            buf.append('\n\nThe browser instead transmitted some file names. '
                       'This was submitted: %s' % ', '.join('"%s"' % x
                            for x in form_matches))
        self.msg = ''.join(buf)

    def __str__(self):
        return self.msg


class FormDataRoutingRedirect(AssertionError):
    def __init__(self, rq):
        exc = rq.routing_exception
        buf = ['A request was sent to this URL (%s) but a redirect was '
               'issued automatically by the routing system to "%s".'
               % (rq.url, exc.new_url)]

        if rq.base_url + '/' == exc.new_url.split('?')[0]:
            buf.append('  The URL was defined with a trailing slash so '
                       'Flak will automatically redirect to the URL '
                       'with the trailing slash if it was accessed '
                       'without one.')

        buf.append('  Make sure to directly send your %s-request to this URL '
                   'since we can\'t make browsers or HTTP clients redirect '
                   'with form data reliably or without user interaction.' %
                   rq.method)
        buf.append('\n\nNote: this exception is only raised in debug mode')
        AssertionError.__init__(self, ''.join(buf).encode('utf-8'))


