# -*- coding: utf-8 -*-
import sys
PY2 = sys.version_info[0] == 2

_identity = lambda x: x

if PY2:
    text_type = unicode
    string_types = (str, unicode)
    integer_types = (int, long)
    iterkeys = lambda d: d.iterkeys()
    itervalues = lambda d: d.itervalues()
    iteritems = lambda d: d.iteritems()
    from cStringIO import StringIO
    exec('def reraise(tp, value, tb=None):\n raise tp, value, tb')
    def implements_to_string(cls):
        cls.__unicode__ = cls.__str__
        cls.__str__ = lambda x: x.__unicode__().encode('utf-8')
        return cls
else:
    text_type = str
    string_types = (str,)
    integer_types = (int,)
    iterkeys = lambda d: iter(d.keys())
    itervalues = lambda d: iter(d.values())
    iteritems = lambda d: iter(d.items())
    from io import StringIO
    implements_to_string = _identity
    def reraise(tp, value, tb=None):
        if value.__traceback__ is not tb:
            raise value.with_traceback(tb)
        raise value


def with_metaclass(meta, *bases):
    # make a dummy metaclass for one level of class instantiation that replaces
    # itself with the actual metaclass.  Because of internal type checks we
    # also need to make sure that we downgrade the custom metaclass for one
    # level to something closer to type (that's why __call__ and __init__ comes
    # back from type etc.).
    #
    # This has the advantage over six.with_metaclass in that it does not
    # introduce dummy classes into the final MRO.
    class metaclass(meta):
        __call__ = type.__call__
        __init__ = type.__init__
        def __new__(cls, name, this_bases, d):
            if this_bases is None:
                return type.__new__(cls, name, (), d)
            return meta(name, bases, d)
    return metaclass('temporary_class', None, {})

