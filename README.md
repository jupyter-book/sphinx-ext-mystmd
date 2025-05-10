# sphinx-ext-mystmd

A Sphinx extension to build MyST-MD AST from a Sphinx project. This can be used for:

1. Embedding API documentation in a MyST project
2. Providing MyST XRef support for a deployed Sphinx project (gradual transition)

Add this extension to your `conf.py` e.g.

```python
extensions = ["sphinx_ext_mystmd"]
```

in order to be able to use the `myst` builder, e.g.

```shell
sphinx-build -b myst . <BUILDDIR>
```

The generated `.myst.json` files in `<BUILDDIR>` can be added to your TOC e.g. using a `pattern` entry, e.g.

```yaml
project:
  toc:
    - file: index.md
    - title: Sphinx Build
      children:
        - pattern: <BUILDDIR>/**.myst.json
```

You can also build an XRef distribution for your site, which allows MyST projects to richly cross-reference into your documentation.

Running

```shell
sphinx-build -b myst-xref . <BUILDDIR>
```

will generate a `myst.xref.json` in `<BUILDDIR>`. The contents of `<BUILDDIR>` should be added to your site's root directory.

> [!WARNING]
> This extension is a literal work-in-progress; some things don't work.
> The intention is to get _something_ on the page before we finalize it.
