# -*- coding: utf-8 -*-
import os
import sys
from threading import Lock, Thread
from functools import update_wrapper
import click
from ._compat import iteritems, reraise


class AppNotFound(click.UsageError):
    pass


def find_best_app(module):
    from .app import Flak

    # search for the most common names first.
    for attr_name in 'app', 'application':
        app = getattr(module, attr_name, None)
        if app is not None and isinstance(app, Flak):
            return app

    # otherwise find the only object that is a flak instance.
    matches = [v for k, v in iteritems(module.__dict__)
               if isinstance(v, Flak)]

    if len(matches) == 1:
        return matches[0]
    raise AppNotFound('Failed to find application in module "%s".  Are '
                      'you sure it contains a Flak application?  Maybe '
                      'you wrapped it in a WSGI middleware or you are '
                      'using a factory function.' % module.__name__)


def prepare_exec_for_file(filename):
    module = []

    if filename.endswith('.py'):
        filename = filename[:-3]
    elif os.path.split(filename)[1] == '__init__.py':
        filename = os.path.dirname(filename)
    else:
        raise AppNotFound('The file provided (%s) does exist but is not a '
                          'valid Python file.  This means that it cannot '
                          'be used as application.  Please change the '
                          'extension to .py' % filename)
    filename = os.path.realpath(filename)

    dirpath = filename
    while 1:
        dirpath, extra = os.path.split(dirpath)
        module.append(extra)
        if not os.path.isfile(os.path.join(dirpath, '__init__.py')):
            break

    sys.path.insert(0, dirpath)
    return '.'.join(module[::-1])


def locate_app(app_id):
    __traceback_hide__ = True
    if ':' in app_id:
        module, app_obj = app_id.split(':', 1)
    else:
        module = app_id
        app_obj = None

    __import__(module)
    mod = sys.modules[module]
    if app_obj is None:
        app = find_best_app(mod)
    else:
        app = getattr(mod, app_obj, None)
        if app is None:
            raise RuntimeError('Failed to find application in module "%s"'
                               % module)

    return app


class DispatchingApp(object):
    '''Special application that dispatches to a flak application which
    is imported by name in a background thread.  If an error happens
    it is is recorded and shows as part of the WSGI handling which in case
    of the Werkzeug debugger means that it shows up in the browser.
    '''

    def __init__(self, loader, use_eager_loading=False):
        self.loader = loader
        self._app = None
        self._lock = Lock()
        self._bg_loading_exc_info = None
        if use_eager_loading:
            self._load_unlocked()
        else:
            self._load_in_background()

    def _load_in_background(self):
        def _load_app():
            __traceback_hide__ = True
            with self._lock:
                try:
                    self._load_unlocked()
                except Exception:
                    self._bg_loading_exc_info = sys.exc_info()
        t = Thread(target=_load_app, args=())
        t.start()

    def _flush_bg_loading_exception(self):
        __traceback_hide__ = True
        exc_info = self._bg_loading_exc_info
        if exc_info is not None:
            self._bg_loading_exc_info = None
            reraise(*exc_info)

    def _load_unlocked(self):
        __traceback_hide__ = True
        self._app = rv = self.loader()
        self._bg_loading_exc_info = None
        return rv

    def __call__(self, environ, start_response):
        __traceback_hide__ = True
        if self._app is not None:
            return self._app(environ, start_response)
        self._flush_bg_loading_exception()
        with self._lock:
            if self._app is not None:
                rv = self._app
            else:
                rv = self._load_unlocked()
            return rv(environ, start_response)


class ScriptInfo(object):
    def __init__(self, app_import_path=None, debug=None, create_app=None):
        #: The application import path
        self.app_import_path = app_import_path
        #: The debug flag.  If this is not None, the application will
        #: automatically have it's debug flag overridden with this value.
        self.debug = debug
        #: Optionally a function that is passed the script info to create
        #: the instance of the application.
        self.create_app = create_app
        #: A dictionary with arbitrary data that can be associated with
        #: this script info.
        self.data = {}
        self._loaded_app = None

    def load_app(self):
        __traceback_hide__ = True
        if self._loaded_app is not None:
            return self._loaded_app
        if self.create_app is not None:
            rv = self.create_app(self)
        else:
            if self.app_import_path is None:
                raise AppNotFound('Could not locate Flak application. '
                                  'You did not provide FLAK_APP or the '
                                  '--app parameter.')
            rv = locate_app(self.app_import_path)
        if self.debug is not None:
            rv.debug = self.debug
        self._loaded_app = rv
        return rv


pass_script_info = click.make_pass_decorator(ScriptInfo, ensure=True)


def with_app(f):
    @click.pass_context
    def decorator(__cx, *args, **kwargs):
        app = __cx.ensure_object(ScriptInfo).load_app()
        return __cx.invoke(f, app, *args, **kwargs)
    return update_wrapper(decorator, f)


def set_debug_value(cx, param, value):
    cx.ensure_object(ScriptInfo).debug = value


def set_app_value(cx, param, value):
    if value is not None:
        if os.path.isfile(value):
            value = prepare_exec_for_file(value)
        elif '.' not in sys.path:
            sys.path.insert(0, '.')
    cx.ensure_object(ScriptInfo).app_import_path = value


debug_option = click.Option(['--debug/--no-debug'],
    help='Enable or disable debug mode.',
    default=None, callback=set_debug_value)


app_option = click.Option(['-a', '--app'],
    help='The application to run',
    callback=set_app_value, is_eager=True)


class CommandGroup(click.Group):
    def command(self, *args, **kwargs):
        wrap_for_cx = kwargs.pop('with_app', True)
        def decorator(f):
            if wrap_for_cx:
                f = with_app(f)
            return click.Group.command(self, *args, **kwargs)(f)
        return decorator

    def group(self, *args, **kwargs):
        kwargs.setdefault('cls', CommandGroup)
        return click.Group.group(self, *args, **kwargs)


class FlakGroup(CommandGroup):
    def __init__(self, add_default_commands=True, add_app_option=None,
                 add_debug_option=True, create_app=None, **extra):
        params = list(extra.pop('params', None) or ())
        if add_app_option is None:
            add_app_option = create_app is None
        if add_app_option:
            params.append(app_option)
        if add_debug_option:
            params.append(debug_option)

        CommandGroup.__init__(self, params=params, **extra)
        self.create_app = create_app

        if add_default_commands:
            self.add_command(run_command)
            self.add_command(shell_command)

    def get_command(self, cx, name):
        # We load built-in commands first as these should always be the
        # same no matter what the app does.  If the app does want to
        # override this it needs to make a custom instance of this group
        # and not attach the default commands.
        #
        # This also means that the script stays functional in case the
        # application completely fails.
        rv = CommandGroup.get_command(self, cx, name)
        if rv is not None:
            return rv

        info = cx.ensure_object(ScriptInfo)
        try:
            rv = info.load_app().cli.get_command(cx, name)
            if rv is not None:
                return rv
        except AppNotFound:
            pass

    def list_commands(self, cx):
        # The commands available is the list of both the application (if
        # available) plus the builtin commands.
        rv = set(click.Group.list_commands(self, cx))
        info = cx.ensure_object(ScriptInfo)
        try:
            rv.update(info.load_app().cli.list_commands(cx))
        except Exception:
            # Here we intentionally swallow all exceptions as we don't
            # want the help page to break if the app does not exist.
            # If someone attempts to use the command we try to create
            # the app again and this will give us the error.
            pass
        return sorted(rv)

    def main(self, *args, **kwargs):
        obj = kwargs.get('obj')
        if obj is None:
            obj = ScriptInfo(create_app=self.create_app)
        kwargs['obj'] = obj
        kwargs.setdefault('auto_envvar_prefix', 'FLAK')
        return CommandGroup.main(self, *args, **kwargs)


def script_info_option(*args, **kwargs):
    try:
        key = kwargs.pop('script_info_key')
    except LookupError:
        raise TypeError('script_info_key not provided.')

    real_callback = kwargs.get('callback')
    def callback(cx, param, value):
        if real_callback is not None:
            value = real_callback(cx, value)
        cx.ensure_object(ScriptInfo).data[key] = value
        return value

    kwargs['callback'] = callback
    kwargs.setdefault('is_eager', True)
    return click.option(*args, **kwargs)


@click.command('run', short_help='Runs a development server.')
@click.option('--host', '-h', default='127.0.0.1',
              help='The interface to bind to.')
@click.option('--port', '-p', default=5000,
              help='The port to bind to.')
@click.option('--reload/--no-reload', default=None,
              help='Enable or disable the reloader.  By default the reloader '
              'is active if debug is enabled.')
@click.option('--debugger/--no-debugger', default=None,
              help='Enable or disable the debugger.  By default the debugger '
              'is active if debug is enabled.')
@click.option('--eager-loading/--lazy-loader', default=None,
              help='Enable or disable eager loading.  By default eager '
              'loading is enabled if the reloader is disabled.')
@click.option('--with-threads/--without-threads', default=False,
              help='Enable or disable multithreading.')
@pass_script_info
def run_command(info, host, port, reload, debugger, eager_loading,
                with_threads):
    '''Runs a local development server for the Flak application.

    This local server is recommended for development purposes only but it
    can also be used for simple intranet deployments.  By default it will
    not support any sort of concurrency at all to simplify debugging.  This
    can be changed with the --with-threads option which will enable basic
    multithreading.

    The reloader and debugger are by default enabled if the debug flag of
    Flak is enabled and disabled otherwise.
    '''
    from werkzeug.serving import run_simple
    if reload is None:
        reload = info.debug
    if debugger is None:
        debugger = info.debug
    if eager_loading is None:
        eager_loading = not reload

    app = DispatchingApp(info.load_app, use_eager_loading=eager_loading)

    # Extra startup messages.  This depends a but on Werkzeug internals to
    # not double execute when the reloader kicks in.
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        # If we have an import path we can print it out now which can help
        # people understand what's being served.  If we do not have an
        # import path because the app was loaded through a callback then
        # we won't print anything.
        if info.app_import_path is not None:
            print(' * Serving Flak app "%s"' % info.app_import_path)
        if info.debug is not None:
            print(' * Forcing debug %s' % (info.debug and 'on' or 'off'))

    run_simple(host, port, app, use_reloader=reload,
               use_debugger=debugger, threaded=with_threads)


@click.command('shell', short_help='Runs a shell in the app context.')
@with_app
def shell_command(app):
    import code
    banner = 'Python %s on %s\nApp: %s%s\nInstance: %s' % (
        sys.version,
        sys.platform,
        app.import_name,
        app.debug and ' [debug]' or '',
        app.instance_path,
    )
    cx = {}

    # Support the regular Python interpreter startup script if someone
    # is using it.
    startup = os.environ.get('PYTHONSTARTUP')
    if startup and os.path.isfile(startup):
        with open(startup, 'r') as f:
            eval(compile(f.read(), startup, 'exec'), cx)

    cx.update(app.make_shell_context())
    code.interact(banner=banner, local=cx)


cli = FlakGroup(help='''\
This shell command acts as general utility script for Flak applications.

It loads the application configured (either through the FLAK_APP environment
variable or the --app parameter) and then provides commands either provided
by the application or Flak itself.

The most useful commands are the "run" and "shell" command.

Example usage:

  flak --app=hello --debug run
''')


def main(as_module=False):
    this_module = __package__ + '.cli'
    args = sys.argv[1:]

    if as_module:
        if sys.version_info >= (2, 7):
            name = 'python -m ' + this_module.rsplit('.', 1)[0]
        else:
            name = 'python -m ' + this_module

        # This module is always executed as "python -m flak.run" and as such
        # we need to ensure that we restore the actual command line so that
        # the reloader can properly operate.
        sys.argv = ['-m', this_module] + sys.argv[1:]
    else:
        name = None

    cli.main(args=args, prog_name=name)


if __name__ == '__main__':
    main(as_module=True)

