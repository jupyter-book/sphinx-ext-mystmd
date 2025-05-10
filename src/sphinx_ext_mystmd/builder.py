from sphinx.builders import Builder
from sphinx.util import logging

import json
import os.path
import pathlib
import hashlib
import urllib.parse

from .transform import MySTNodeVisitor
from .utils import to_text, find_by_type, breadth_first_walk, title_to_name


logger = logging.getLogger(__name__)


class MySTBuilderMixin:
    def transform_internal_links(self, node):
        """
        Rewrite internal document links to point to the anticipated MyST JSON document path

        :param node: docutils tree
        """
        docnames = set(self.env.found_docs)
        for link in find_by_type("link", node):
            parsed_uri = urllib.parse.urlparse(link["url"])
            if parsed_uri.scheme or not parsed_uri.path:
                continue
            if parsed_uri.path not in docnames:
                continue
            # Add JSON suffix to path
            # TODO: what happens for the xref case? what do the links do?
            new_path = f"{parsed_uri.path}.myst.json"
            link["url"] = urllib.parse.urlunparse(parsed_uri._replace(path=new_path))


class MySTBuilder(MySTBuilderMixin, Builder):
    name = "myst"

    def _slugify(self, path):
        name = os.path.basename(path)
        return title_to_name(name)

    def _get_output_path(self, doc_name):
        target_stem = self._slugify(doc_name)
        return os.path.join(self.outdir, f"{target_stem}.myst.json")

    def prepare_writing(self, docnames):
        logger.info(f"About to write {docnames}")

    def get_outdated_docs(self):
        for docname in self.env.found_docs:
            if docname not in self.env.all_docs:
                yield docname
                continue

            # Determine age of target
            target_path = self._get_output_path(docname)
            try:
                targetmtime = os.path.getmtime(target_path)
            except Exception:
                targetmtime = 0

            # Determine if source is newer than target
            source_path = self.env.doc2path(docname)
            try:
                srcmtime = os.path.getmtime(source_path)
                if srcmtime > targetmtime:
                    yield docname
            except OSError:
                # source doesn't exist anymore
                pass

    def write_doc(self, docname, doctree):
        visitor = MySTNodeVisitor(doctree)
        mdast = visitor.visit_with_result(doctree)

        self.transform_internal_links(mdast)

        output_path = pathlib.Path(self._get_output_path(docname))
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(
                {
                    "kind": "Article",
                    "mdast": mdast,
                },
                f,
                indent=2,
            )

    def get_target_uri(self, docname, typ=None):
        return self._slugify(docname)


class MySTXRefBuilder(MySTBuilderMixin, Builder):
    name = "myst-xref"

    def _slugify(self, path):
        name = os.path.basename(path)
        return title_to_name(name)

    def _get_xref_path(self, doc_name):
        target_stem = self._slugify(doc_name)
        return os.path.join(self.outdir, "content", f"{target_stem}.json")

    def prepare_writing(self, docnames):
        logger.info(f"About to write {docnames}")

    def get_outdated_docs(self):
        for docname in self.env.found_docs:
            if docname not in self.env.all_docs:
                yield docname
                continue
            target_path = self._get_xref_path(docname)
            try:
                targetmtime = os.path.getmtime(target_path)
            except Exception:
                targetmtime = 0
            try:
                srcmtime = os.path.getmtime(self.env.doc2path(docname))
                if srcmtime > targetmtime:
                    yield docname
            except OSError:
                # source doesn't exist anymore
                pass

    def write_doc(self, docname, doctree):
        visitor = MySTNodeVisitor(doctree)
        mdast = doctree.walkabout(visitor)

        self.transform_internal_links(mdast)

        slug = self._slugify(docname)
        xref_path = self._get_xref_path(docname)

        json_xref_dst = pathlib.Path(xref_path)
        json_xref_dst.parent.mkdir(exist_ok=True)

        with open(self.env.doc2path(docname), "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()

        heading = next(find_by_type("heading", mdast), None)
        if heading is not None:
            title = to_text(heading)
        else:
            title = None

        with open(json_xref_dst, "w") as f:
            json.dump(
                {
                    "kind": "Article",
                    "sha256": sha256,
                    "slug": slug,
                    "location": f"/{docname}",
                    "dependencies": [],
                    "frontmatter": {
                        "title": title,
                        "content_includes_title": title is not None,
                    },
                    "mdast": mdast,
                    "references": {"cite": {"order": [], "data": {}}},
                },
                f,
                indent=2,
            )

    def _xref_kind_for_node(self, node):
        if node["type"] == "container":
            return node.get("kind", "figure")
        if "kind" in node:
            return f"{node['type']}:{node['kind']}"
        return node["type"]

    def _get_written_target_references(self, doc):
        path = self._get_xref_path(doc)
        slug = self._slugify(doc)

        with open(path, "r") as f:
            data = json.load(f)

        mdast = data["mdast"]
        for node in breadth_first_walk(mdast):
            if "identifier" in node:
                yield {
                    "identifier": node["identifier"],
                    "kind": self._xref_kind_for_node(node),
                    "data": self._get_xref_path(doc),
                    "url": f"/{slug}",
                }

    def finish(self):
        page_references = [
            {
                "kind": "page",
                "url": f"/{self._slugify(n)}",
                "data": self._get_xref_path(n),
            }
            for n in self.env.found_docs
        ]
        target_references = [
            ref
            for refs in (
                self._get_written_target_references(n) for n in self.env.found_docs
            )
            for ref in refs
        ]
        references = [*page_references, *target_references]

        xref = {"version": "1", "myst": "1.3.6", "references": references}
        with open(os.path.join(self.outdir, "myst.xref.json"), "w") as f:
            json.dump(xref, f, indent=2)

    def get_target_uri(self, docname, typ=None):
        return self._slugify(docname)
