# -*- coding: utf-8 -*-
import flak
import os
import sys
import pkgutil
import pytest
import textwrap

@pytest.fixture
def test_apps(monkeypatch):
    monkeypatch.syspath_prepend(
        os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'test_apps'))
    )

@pytest.fixture(params=(True, False))
def limit_loader(request, monkeypatch):
    if not request.param:
        return

    class LimitedLoader(object):
        def __init__(self, loader):
            self.loader = loader

        def __getattr__(self, name):
            if name in ('archive', 'get_filename'):
                msg = 'Mocking a loader which does not have `%s.`' % name
                raise AttributeError(msg)
            return getattr(self.loader, name)

    old_get_loader = pkgutil.get_loader

    def get_loader(*args, **kwargs):
        return LimitedLoader(old_get_loader(*args, **kwargs))
    monkeypatch.setattr(pkgutil, 'get_loader', get_loader)


@pytest.fixture
def modules_tmpdir(tmpdir, monkeypatch):
    rv = tmpdir.mkdir('modules_tmpdir')
    monkeypatch.syspath_prepend(str(rv))
    return rv


@pytest.fixture
def modules_tmpdir_prefix(modules_tmpdir, monkeypatch):
    monkeypatch.setattr(sys, 'prefix', str(modules_tmpdir))
    return modules_tmpdir


@pytest.fixture
def site_packages(modules_tmpdir, monkeypatch):
    rv = modules_tmpdir \
        .mkdir('lib')\
        .mkdir('python{x[0]}.{x[1]}'.format(x=sys.version_info))\
        .mkdir('site-packages')
    monkeypatch.syspath_prepend(str(rv))
    return rv


@pytest.fixture
def install_egg(modules_tmpdir, monkeypatch):
    def inner(name, base=modules_tmpdir):
        if not isinstance(name, str):
            raise ValueError(name)
        base.join(name).ensure_dir()
        base.join(name).join('__init__.py').ensure()

        egg_setup = base.join('setup.py')
        egg_setup.write(textwrap.dedent('''
        from setuptools import setup
        setup(name='{0}',
              version='1.0',
              packages=['site_egg'],
              zip_safe=True)
        '''.format(name)))

        import subprocess
        subprocess.check_call(
            [sys.executable, 'setup.py', 'bdist_egg'],
            cwd=str(modules_tmpdir)
        )
        egg_path, = modules_tmpdir.join('dist/').listdir()
        monkeypatch.syspath_prepend(str(egg_path))
        return egg_path
    return inner


@pytest.fixture
def purge_module(request):
    def inner(name):
        request.addfinalizer(lambda: sys.modules.pop(name, None))
    return inner


@pytest.fixture
def catch_deprecation_warnings():
    import warnings
    warnings.simplefilter('default', category=DeprecationWarning)
    return lambda: warnings.catch_warnings(record=True)

