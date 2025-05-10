from .builder import MySTBuilder, MySTXRefBuilder


def setup(app):
    app.add_builder(MySTBuilder)
    app.add_builder(MySTXRefBuilder)
