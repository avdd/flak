# -*- coding: utf-8 -*-
from ._compat import with_metaclass

http_methods = frozenset(['get', 'post', 'head', 'options',
                          'delete', 'put', 'trace', 'patch'])


class View(object):
    methods = None
    decorators = ()

    def dispatch_request(self, cx):
        raise NotImplementedError()

    @classmethod
    def as_view(cls, name, *class_args, **class_kwargs):
        def view(cx, *args, **kwargs):
            self = view.view_class(*class_args, **class_kwargs)
            return self.dispatch_request(cx, *args, **kwargs)

        if cls.decorators:
            view.__name__ = name
            view.__module__ = cls.__module__
            for decorator in cls.decorators:
                view = decorator(view)

        view.view_class = cls
        view.methods = cls.methods
        view.__name__ = name
        view.__doc__ = cls.__doc__
        view.__module__ = cls.__module__
        return view


class MethodViewType(type):
    def __new__(cls, name, bases, d):
        rv = type.__new__(cls, name, bases, d)
        if 'methods' not in d:
            methods = set(rv.methods or [])
            for key in d:
                if key in http_methods:
                    methods.add(key.upper())
            # If we have no method at all in there we don't want to
            # add a method list.  (This is for instance the case for
            # the base class or another subclass of a base method view
            # that does not introduce new methods).
            if methods:
                rv.methods = sorted(methods)
        return rv


class MethodView(with_metaclass(MethodViewType, View)):
    def dispatch_request(self, cx, *args, **kwargs):
        meth = getattr(self, cx.request.method.lower(), None)
        if meth is None and cx.request.method == 'HEAD':
            meth = getattr(self, 'get', None)
        assert meth is not None, 'Unimplemented method %r' % cx.request.method
        return meth(cx, *args, **kwargs)

