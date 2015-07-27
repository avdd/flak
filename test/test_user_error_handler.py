# -*- coding: utf-8 -*-
from werkzeug.exceptions import Forbidden, InternalServerError
from flak import Flak


def test_error_handler_no_match():
    app = Flak(__name__)

    class CustomException(Exception):
        pass

    @app.errorhandler(CustomException)
    def custom_exception_handler(cx, e):
        assert isinstance(e, CustomException)
        return 'custom'

    @app.errorhandler(500)
    def handle_500(cx, e):
        return type(e).__name__

    @app.route('/custom')
    def custom_test(cx):
        raise CustomException()

    @app.route('/keyerror')
    def key_error(cx):
        raise KeyError()

    c = app.test_client()

    assert c.get('/custom').data == b'custom'
    assert c.get('/keyerror').data == b'KeyError'


def test_error_handler_subclass():
    app = Flak(__name__)

    class ParentException(Exception):
        pass

    class ChildExceptionUnregistered(ParentException):
        pass

    class ChildExceptionRegistered(ParentException):
        pass

    @app.errorhandler(ParentException)
    def parent_exception_handler(cx, e):
        assert isinstance(e, ParentException)
        return 'parent'

    @app.errorhandler(ChildExceptionRegistered)
    def child_exception_handler(cx, e):
        assert isinstance(e, ChildExceptionRegistered)
        return 'child-registered'

    @app.route('/parent')
    def parent_test(cx):
        raise ParentException()

    @app.route('/child-unregistered')
    def unregistered_test(cx):
        raise ChildExceptionUnregistered()

    @app.route('/child-registered')
    def registered_test(cx):
        raise ChildExceptionRegistered()

    c = app.test_client()

    assert c.get('/parent').data == b'parent'
    assert c.get('/child-unregistered').data == b'parent'
    assert c.get('/child-registered').data == b'child-registered'


def test_error_handler_http_subclass():
    app = Flak(__name__)

    class ForbiddenSubclassRegistered(Forbidden):
        pass

    class ForbiddenSubclassUnregistered(Forbidden):
        pass

    @app.errorhandler(403)
    def code_exception_handler(cx, e):
        assert isinstance(e, Forbidden)
        return 'forbidden'

    @app.errorhandler(ForbiddenSubclassRegistered)
    def subclass_exception_handler(cx, e):
        assert isinstance(e, ForbiddenSubclassRegistered)
        return 'forbidden-registered'

    @app.route('/forbidden')
    def forbidden_test(cx):
        raise Forbidden()

    @app.route('/forbidden-registered')
    def registered_test(cx):
        raise ForbiddenSubclassRegistered()

    @app.route('/forbidden-unregistered')
    def unregistered_test(cx):
        raise ForbiddenSubclassUnregistered()

    c = app.test_client()

    assert c.get('/forbidden').data == b'forbidden'
    assert c.get('/forbidden-unregistered').data == b'forbidden'
    assert c.get('/forbidden-registered').data == b'forbidden-registered'


