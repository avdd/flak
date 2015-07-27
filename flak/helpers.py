# -*- coding: utf-8 -*-
import os
import sys
import pkgutil
import posixpath
import mimetypes
from time import time
from zlib import adler32
from threading import RLock
from werkzeug.routing import BuildError
from functools import update_wrapper

from werkzeug.urls import url_quote
from werkzeug.datastructures import Headers
from werkzeug.exceptions import NotFound
from werkzeug.wsgi import wrap_file

from ._compat import string_types, text_type


_sentinel = object()


def _is_package(loader, mod_name):
    if hasattr(loader, 'is_package'):
        return loader.is_package(mod_name)
    elif (loader.__class__.__module__ == '_frozen_importlib' and
          loader.__class__.__name__ == 'NamespaceLoader'):
        return True
    msg = ('%s.is_package() method is missing but is required by Flak of '
           'PEP 302 import hooks.  If you do not use import hooks and '
           'you encounter this error please file a bug against Flak')
    raise AttributeError(msg % loader.__class__.__name__)


def find_package(import_name):
    """Finds a package and returns the prefix (or None if the package is
    not installed) as well as the folder that contains the package or
    module as a tuple.  The package path returned is the module that would
    have to be added to the pythonpath in order to make it possible to
    import the module.  The prefix is the path below which a UNIX like
    folder structure exists (lib, share etc.).
    """
    root_mod_name = import_name.split('.')[0]
    loader = pkgutil.get_loader(root_mod_name)
    if loader is None or import_name == '__main__':
        # import name is not found, or interactive/main module
        package_path = os.getcwd()
    else:
        # For .egg, zipimporter does not have get_filename until Python 2.7.
        if hasattr(loader, 'get_filename'):
            filename = loader.get_filename(root_mod_name)
        elif hasattr(loader, 'archive'):
            # zipimporter's loader.archive points to the .egg or .zip
            # archive filename is dropped in call to dirname below.
            filename = loader.archive
        else:
            # At least one loader is missing both get_filename and archive:
            # Google App Engine's HardenedModulesHook
            #
            # Fall back to imports.
            __import__(import_name)
            filename = sys.modules[import_name].__file__
        package_path = os.path.abspath(os.path.dirname(filename))

        # In case the root module is a package we need to chop of the
        # rightmost part.  This needs to go through a helper function
        # because of python 3.3 namespace packages.
        if _is_package(loader, root_mod_name):
            package_path = os.path.dirname(package_path)

    site_parent, site_folder = os.path.split(package_path)
    py_prefix = os.path.abspath(sys.prefix)
    if package_path.startswith(py_prefix):
        return py_prefix, package_path
    elif site_folder.lower() == 'site-packages':
        parent, folder = os.path.split(site_parent)
        # Windows like installations
        if folder.lower() == 'lib':
            base_dir = parent
        # UNIX like installations
        elif os.path.basename(parent).lower() == 'lib':
            base_dir = os.path.dirname(parent)
        else:
            base_dir = site_parent
        return base_dir, package_path
    return None, package_path


def _endpoint_from_view_func(view_func):
    assert view_func is not None, 'expected function'
    return view_func.__name__


class locked_cached_property(object):
    def __init__(self, func):
        self.__name__ = func.__name__
        self.__module__ = func.__module__
        self.__doc__ = func.__doc__
        self.func = func
        self.lock = RLock()

    def __get__(self, obj, _=None):
        if obj is None:
            return self
        with self.lock:
            value = obj.__dict__.get(self.__name__, _sentinel)
            if value is _sentinel:
                value = self.func(obj)
                obj.__dict__[self.__name__] = value
            return value


def get_root_path(import_name):
    # Module already imported and has a file attribute.  Use that first.
    mod = sys.modules.get(import_name)
    if mod is not None and hasattr(mod, '__file__'):
        return os.path.dirname(os.path.abspath(mod.__file__))

    # Next attempt: check the loader.
    loader = pkgutil.get_loader(import_name)

    # Loader does not exist or we're referring to an unloaded main module
    # or a main module without path (interactive sessions), go with the
    # current working directory.
    if loader is None or import_name == '__main__':
        return os.getcwd()

    # For .egg, zipimporter does not have get_filename until Python 2.7.
    # Some other loaders might exhibit the same behavior.
    if hasattr(loader, 'get_filename'):
        filepath = loader.get_filename(import_name)
    else:
        # Fall back to imports.
        __import__(import_name)
        mod = sys.modules[import_name]
        filepath = getattr(mod, '__file__', None)

        # If we don't have a filepath it might be because we are a
        # namespace package.  In this case we pick the root path from the
        # first module that is contained in our package.
        if filepath is None:
            raise RuntimeError('No root path can be found for the provided '
                               'module "%s".  This can happen because the '
                               'module came from an import hook that does '
                               'not provide file name information or because '
                               'it\'s a namespace package.  In this case '
                               'the root path needs to be explicitly '
                               'provided.' % import_name)

    # filepath is import_name.py for a module, or __init__.py for a package.
    return os.path.dirname(os.path.abspath(filepath))


def _url_for(cx, endpoint, values):
    url_adapter = cx.url_adapter
    app = cx.app

    if cx.request:
        external = values.pop('_external', False)

    else:
        if url_adapter is None:
            raise RuntimeError('Application was not able to create a URL '
                               'adapter for request independent URL generation. '
                               'You might be able to fix this by setting '
                               'the SERVER_NAME config variable.')
        external = values.pop('_external', True)

    anchor = values.pop('_anchor', None)
    method = values.pop('_method', None)
    scheme = values.pop('_scheme', None)
    app.inject_url_defaults(cx, endpoint, values)

    if scheme is not None:
        if not external:
            raise ValueError('When specifying _scheme, _external must be True')
        url_adapter.url_scheme = scheme

    try:
        rv = url_adapter.build(endpoint, values, method=method,
                               force_external=external)
    except BuildError as error:
        # inject again for error callback
        values['_external'] = external
        values['_anchor'] = anchor
        values['_method'] = method
        return app.handle_url_build_error(cx, error, endpoint, values)

    if anchor is not None:
        rv += '#' + url_quote(anchor)
    return rv


