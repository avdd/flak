# -*- coding: utf-8 -*-

def fake_namespace():
    class Namespace(object):
        def signal(self, name, doc=None):
            return _FakeSignal(name, doc)

    class _FakeSignal(object):
        def __init__(self, name, doc=None):
            self.name = name
            self.__doc__ = doc
        def send(*a, **k):
            pass
        def _fail(self, *args, **kwargs):
            raise RuntimeError('signalling support is unavailable '
                               'because the blinker library is '
                               'not installed.')
        connect = disconnect = has_receivers_for = receivers_for = \
                  temporarily_connected_to = connected_to = _fail
        del _fail
    return Namespace

try:
    from blinker import Namespace
except ImportError:
    Namespace = fake_namespace()

_signals = Namespace()
request_started = _signals.signal('request-started')
request_finished = _signals.signal('request-finished')
context_created = _signals.signal('context-created')
context_teardown = _signals.signal('context-teardown')
request_exception = _signals.signal('request-exception')

