# -*- coding: utf-8 -*-
from __future__ import absolute_import
import sys
from logging import getLogger, getLoggerClass,  \
                    StreamHandler, Formatter,   \
                    DEBUG, ERROR


PROD_LOG_FORMAT = '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
DEBUG_LOG_FORMAT = (
    '-' * 80 + '\n' +
    '%(levelname)s in %(module)s [%(pathname)s:%(lineno)d]:\n' +
    '%(message)s\n' +
    '-' * 80
)


def _should_log_for(app, mode):
    policy = app.config['LOGGER_HANDLER_POLICY']
    if policy == mode or policy == 'always':
        return True
    return False


def create_logger(app):
    """Creates a logger for the given application.  This logger works
    similar to a regular Python logger but changes the effective logging
    level based on the application's debug flag.  Furthermore this
    function also removes all attached handlers in case there was a
    logger with the log name before.
    """
    Logger = getLoggerClass()

    class DebugLogger(Logger):
        def getEffectiveLevel(self):
            if self.level == 0 and app.debug:
                return DEBUG
            return Logger.getEffectiveLevel(self)

    class DebugHandler(StreamHandler):
        def emit(self, record):
            if app.debug and _should_log_for(app, 'debug'):
                StreamHandler.emit(self, record)

    class ProductionHandler(StreamHandler):
        def emit(self, record):
            if not app.debug and _should_log_for(app, 'production'):
                StreamHandler.emit(self, record)

    debug = DebugHandler()
    debug.setLevel(DEBUG)
    debug.setFormatter(Formatter(DEBUG_LOG_FORMAT))

    production = ProductionHandler(sys.stderr)
    production.setLevel(ERROR)
    production.setFormatter(Formatter(PROD_LOG_FORMAT))

    logger = getLogger(app.logger_name)
    del logger.handlers[:]
    logger.__class__ = DebugLogger
    logger.addHandler(debug)
    logger.addHandler(production)
    return logger

