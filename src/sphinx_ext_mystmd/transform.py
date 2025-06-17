import contextlib
from docutils.nodes import NodeVisitor, SkipChildren, SkipSiblings
from weakref import WeakKeyDictionary
import inspect
from sphinx.util import logging


from .utils import normalize_label


logger = logging.getLogger(__name__)


def is_context_manager(obj):
    return hasattr(obj, "__enter__")


class Visitor(NodeVisitor):
    def __init__(self, document):
        super().__init__(document)

        self._visited = WeakKeyDictionary()
        self._stack = []

    def dispatch_visit(self, node):
        visitor_name = f"visit_{node.__class__.__name__}"
        impl = getattr(self, visitor_name)

        # Invoke visitor
        instruction_or_ctx_like = impl(node)
        if is_context_manager(instruction_or_ctx_like):
            maybe_instruction = instruction_or_ctx_like.__enter__()
        elif inspect.isgenerator(instruction_or_ctx_like):
            maybe_instruction = next(instruction_or_ctx_like)
        else:
            maybe_instruction = instruction_or_ctx_like

        # Allow context managers to use control flow without preventing cleanup
        self._visited[node] = instruction_or_ctx_like
        self._stack.append(node)

        if maybe_instruction in (SkipChildren, SkipSiblings):
            raise maybe_instruction

    def dispatch_departure(self, node):
        try:
            gen_or_ctx_like = self._visited.pop(node)
        except KeyError:
            return

        self._stack.pop()

        # Exit result generator
        if is_context_manager(gen_or_ctx_like):
            gen_or_ctx_like.__exit__(None, None, None)
        elif inspect.isgenerator(gen_or_ctx_like):
            next(gen_or_ctx_like, None)

    @property
    def parent_node(self):
        return self._stack[-1] if self._stack else None


class MySTNodeVisitor(Visitor):
    def __init__(self, document):
        super().__init__(document)

        self._heading_depth = 0
        self._next_sibling_id = None

        self._result = None
        self._result_stack = []

    @property
    def parent_result(self):
        return self._result_stack[-1] if self._result_stack else None

    def visit_with_result(self, doctree):
        doctree.walkabout(self)
        return self._result

    def inherit_node_info(self, node, docutils_node):
        ids = docutils_node.get("ids", [])
        if ids:
            longest_id = max(ids, key=len)
            if len(ids) > 1:
                print(f"Warning, found multiple ids: {ids}, using {longest_id}")

            identifier, label, _ = normalize_label(longest_id)
            node["identifier"] = identifier
            node["label"] = label

    def push_myst_node(self, node, docutils_node=None):
        self.parent_result["children"].append(node)
        if docutils_node is not None:
            self.inherit_node_info(node, docutils_node)

    @contextlib.contextmanager
    def enter_myst_node(self, node, docutils_node=None):
        if self._result_stack:
            parent = self._result_stack[-1]
            parent["children"].append(node)

        self._result_stack.append(node)
        if docutils_node is not None:
            self.inherit_node_info(node, docutils_node)
        try:
            yield node
        finally:
            self._result_stack.pop()

    def visit_meta(self, node):
        logger.warning("`meta` node not implemented")

    def visit_container(self, node):
        return self.enter_myst_node({"type": "container", "children": []})

    def visit_comment(self, node):
        with self.enter_myst_node(
            {
                "type": "comment",
                "value": str(node.children[0]) if node.children else "",
            },
            node,  # TODO: totext
        ):
            yield SkipChildren

    def visit_raw(self, node):
        return self.enter_myst_node(
            {"type": "paragraph", "children": [{"type": "text", "value": str(node)}]}
        )

    def visit_compact_paragraph(self, node):
        return self.enter_myst_node({"type": "paragraph", "children": []}, node)

    def visit_inline(self, node):
        return self.enter_myst_node(
            {"type": "span", "class": node.get("classes"), "children": []}, node
        )

    def visit_reference(self, node):
        if node.get("refid"):
            return self.enter_myst_node(
                {"type": "link", "url": f"#{node['refid']}", "children": []}, node
            )
        elif node.get("refuri"):
            return self.enter_myst_node(
                {"type": "link", "url": node["refuri"], "children": []}, node
            )
        else:
            raise

    visit_number_reference = visit_reference

    def visit_topic(self, node):
        return self.enter_myst_node({"type": "admonition", "children": []}, node)

    def visit_problematic(self, node):
        return self.enter_myst_node(
            {"type": "span", "class": "problematic", "children": []}, node
        )

    def visit_tgroup(self, node):
        logger.warning("Encountered `tgroup` node, ignoring in favour of children")
        return

    def visit_colspec(self, node):
        logger.warning("`colspec` node not implemented")
        return SkipChildren

    def visit_math(self, node):
        return self.enter_myst_node({"type": "inlineMath", "children": []}, node)

    def visit_math_block(self, node):
        return self.enter_myst_node({"type": "math", "children": []}, node)

    def visit_target(self, node):
        logger.warning("`target` node not implemented")

    @contextlib.contextmanager
    def enter_heading(self):
        depth, self._heading_depth = self._heading_depth, self._heading_depth + 1
        try:
            yield
        finally:
            self._heading_depth = depth

    def visit_title(self, node):
        parent_type = self.parent_node.__class__.__name__
        if parent_type == "section":
            with self.enter_myst_node(
                {"type": "heading", "depth": self._heading_depth, "children": []}, node
            ):
                yield
        elif parent_type == "table":
            with self.enter_myst_node({"type": "caption", "children": []}, node):
                yield
        elif parent_type == "compact_paragraph":
            with self.enter_myst_node(
                {"type": "span", "class": "sphinx-caption-text", "children": []}, node
            ):
                yield
        elif parent_type in {"topic", "admonition", "sidebar"}:
            with self.enter_myst_node(
                {
                    "type": "admonitionTitle",
                    "children": [],
                }
            ):
                yield
        else:
            raise NotImplementedError(parent_type)

    def visit_enumerated_list(self, node):
        return self.enter_myst_node(
            {"type": "list", "ordered": True, "children": []}, node
        )

    def visit_substition_definition(self, node):
        logger.warning("`substitution_definition` node not implemented")
        return SkipChildren

    def visit_subtitle(self, node):
        with self.enter_myst_node(
            {"type": "heading", "depth": self._heading_depth + 1, "children": []}, node
        ):
            with self.enter_heading():
                yield

    def visit_bullet_list(self, node):
        return self.enter_myst_node({"type": "list", "children": []}, node)

    def visit_rubric(self, node):
        with self.enter_myst_node({"type": "paragraph", "children": []}, node):
            with self.enter_myst_node({"type": "strong", "children": []}):
                self.push_myst_node({"type": "text", "value": str(node.children[0])})
                yield SkipChildren

    def visit_transition(self, node):
        return self.enter_myst_node({"type": "thematicBreak"})

    def visit_list_item(self, node):
        return self.enter_myst_node({"type": "listItem", "children": []}, node)

    def visit_emphasis(self, node):
        return self.enter_myst_node({"type": "emphasis", "children": []}, node)

    def visit_strong(self, node):
        return self.enter_myst_node({"type": "strong", "children": []}, node)

    def visit_subscript(self, node):
        self.push_myst_node({"type": "html", "value": "<sub>"})
        yield
        self.push_myst_node({"type": "html", "value": "</sub>"})

    def visit_superscript(self, node):
        self.push_myst_node({"type": "html", "value": "<sup>"})
        yield
        self.push_myst_node({"type": "html", "value": "</sup>"})

    def visit_literal(self, node):
        return self.enter_myst_node({"type": "inlineCode", "children": []}, node)

    def visit_literal_emphasis(self, node):
        with self.enter_myst_node({"type": "emphasis", "children": []}, node):
            with self.enter_myst_node({"type": "inlineCode", "children": []}):
                yield

    def visit_literal_strong(self, node):
        with self.enter_myst_node({"type": "strong", "children": []}, node):
            with self.enter_myst_node({"type": "inlineCode", "children": []}):
                yield

    def visit_footnote_reference(self, node):
        return self.enter_myst_node(
            {"type": "link", "url": "#", "children": []}, node
        )  # TODO: fix url

    def visit_index(self, node):
        logger.warning("`index` node not implemented")
        return SkipChildren

    def visit_title_reference(self, node):
        return self.enter_myst_node(  # TODO fix url
            {"type": "link", "url": "#", "children": []}, node
        )

    def visit_sidebar(self, node):
        return self.enter_myst_node(
            {"type": "aside", "kind": "sidebar", "children": []}, node
        )

    def visit_image(self, node):
        return self.enter_myst_node({"type": "image", "url": node["uri"]})

    def visit_paragraph(self, node):
        return self.enter_myst_node({"type": "paragraph", "children": []}, node)

    def visit_Text(self, node):
        return self.enter_myst_node({"type": "text", "value": str(node)})

    # visit_XXX admonitions (see loop below)

    def visit_section(self, node):
        with self.enter_myst_node({"type": "block", "children": []}, node):
            with self.enter_heading():
                yield

    def visit_document(self, node):
        with self.enter_myst_node({"type": "root", "children": []}, node) as result:
            yield

        self._result = result

    def visit_generated(self, node):
        logger.warning("`generated` node not implemented")
        return SkipChildren

    def visit_classifier(self, node):
        logger.warning("`classifier` node not implemented")
        return SkipChildren

    def visit_definition_list(self, node):
        return self.enter_myst_node({"type": "definitionList", "children": []}, node)

    def visit_definition(self, node):
        return self.enter_myst_node(
            {"type": "definitionDescription", "children": []}, node
        )

    def visit_term(self, node):
        return self.enter_myst_node({"type": "definitionTerm", "children": []}, node)

    def visit_definition_list_item(self, node):
        return

    def visit_option_list(self, node):
        logger.warning("`option_list` node not implemented")
        return SkipChildren

    def visit_line_block(self, node):
        logger.warning("`line_block` node not implemented")
        return SkipChildren

    def visit_doctest_block(self, node):
        self.push_myst_node({"type": "code", "value": str(node.children[0])}, node)
        return SkipChildren

    def visit_table(self, node):
        return self.enter_myst_node({"type": "table", "children": []}, node)

    def visit_tbody(self, node):
        logger.warning("Encountered `tbody` node, ignoring in favour of children")

    def visit_autosummary_table(self, node):
        logger.warning(
            "Encountered `autosummary_table` node, ignoring in favor of children"
        )

    def visit_autosummary_toc(self, node):
        logger.warning("Encountered `autosummary_table` node, skipping")
        return SkipChildren

    def visit_glossary(self, node):
        return self.enter_myst_node({"type": "glossary", "children": []}, node)

    def visit_row(self, node):
        return self.enter_myst_node({"type": "tableRow", "children": []}, node)

    def visit_entry(self, node):
        return self.enter_myst_node({"type": "tableCell", "children": []}, node)

    def visit_footnote(self, node):
        return self.enter_myst_node(
            {"type": "footnoteDefinition", "children": []}, node
        )

    def visit_label(self, node):
        logger.warning("`label` node not implemented")
        return SkipChildren

    def visit_citation(self, node):
        logger.warning("`citation` node not implemented")
        return SkipChildren

    def visit_legend(self, node):
        logger.warning("`legend` node not implemented")
        return SkipChildren

    def visit_caption(self, node):
        return self.enter_myst_node(
            {"type": "caption", "kind": "figure", "children": []}, node
        )

    def visit_figure(self, node):
        return self.enter_myst_node(
            {"type": "container", "kind": "figure", "children": []}, node
        )

    def visit_thead(self, node):
        table = self.parent_result
        children = table["children"]
        n_children = len(children)

        yield

        new_children = children[n_children:]

        for child in new_children:
            assert child["type"] == "tableRow"
            for row_child in child["children"]:
                row_child["header"] = True

    def visit_tabular_col_spec(self, node):
        logger.warning("`tabular_colspec` node not implemented")
        return SkipChildren

    def visit_literal_block(self, node):
        self.push_myst_node({"type": "code", "value": str(node.children[0])}, node)
        return SkipChildren

    def visit_block_quote(self, node):
        return self.enter_myst_node({"type": "blockquote", "children": []}, node)

    def visit_attribution(self, node):
        return self.enter_myst_node({"type": "caption", "children": []}, node)

    def visit_admonition(self, node):
        return self.enter_myst_node({"type": "admonition", "children": []}, node)

    def visit_versionmodified(self, node):
        logger.info(repr(node))
        return self.enter_myst_node(
            {
                "type": "admonition",
                "children": [
                    {
                        "type": "admonitionTitle",
                        "children": [{"type": "text", "value": "Version Modified"}],
                    }
                ],
            },
            node,
        )

    def visit_productionlist(self, node):
        return self.enter_myst_node(
            {
                "type": "admonition",
                "children": [
                    {
                        "type": "admonitionTitle",
                        "children": [{"type": "text", "value": "Version Modified"}],
                    }
                ],
            },
            node,
        )

    def visit_substitution_definition(self, node):
        # TODO: cache this?

        logger.warning("`substitution_definition` node not implemented")
        return SkipChildren

    def visit_compound(self, node):
        return self.enter_myst_node(
            {"type": "div", "children": []}, node
        )  # TODO: proper container?

    def visit_field_list(self, node):
        return self.enter_myst_node(
            {
                "type": "definitionList",
                "children": [],
                # "class": "sphinx-field-list"
            },
            node,
        )

    def visit_field_name(self, node):
        return self.enter_myst_node(
            {
                "type": "definitionTerm",
                "children": [],
                # "class": "sphinx-field-name"
            },
            node,
        )

    def visit_field_body(self, node):
        return self.enter_myst_node(
            {
                "type": "definitionDescription",
                "children": [],
                # "class": "sphinx-field-body",
            },
            node,
        )

    def visit_desc(self, node):
        return self.enter_myst_node(
            {
                "type": "definitionList",
                "children": [],  # "class": "sphinx-desc"
            },
            node,
        )

    def visit_desc_content(self, node):
        return self.enter_myst_node(
            {
                "type": "definitionDescription",
                "children": [],
                # "class": "sphinx-desc-content",
            },
            node,
        )

    def visit_desc_signature(self, node):
        return self.enter_myst_node(
            {
                "type": "definitionTerm",
                "children": [],
                # "class": "sphinx-desc-signature",
            },
            node,
        )

    def visit_desc_parameterlist(self, node):
        with self.enter_myst_node(
            {"type": "span", "children": [], "class": "sphinx-desc-parameterlist"}, node
        ) as parent:
            yield
            if parent["children"]:
                *leading, last = parent["children"]
                parent["children"] = [
                    {"type": "text", "value": "("},
                    *[
                        x
                        for p in [(n, {"type": "text", "value": ", "}) for n in leading]
                        for x in p
                    ],
                    last,
                    {"type": "text", "value": ")"},
                ]
            else:
                parent["children"] = [
                    {"type": "text", "value": "("},
                    {"type": "text", "value": ")"},
                ]

    def visit_desc_parameter(self, node):
        return self.enter_myst_node(
            {
                "type": "emphasis",
                "children": [],
                #                "class": "sphinx-desc-parameter",
            },
            node,
        )

    def visit_desc_annotation(self, node):
        return self.enter_myst_node(
            {"type": "emphasis", "children": [], "class": "sphinx-desc-annotation"},
            node,
        )

    def visit_field(self, node):
        return  # Render children

    def _visit_span(self, node):
        name = type(node).__name__
        escaped_name = name.replace("_", "-")
        return self.enter_myst_node(
            {"type": "span", "children": [], "class": f"sphinx-{escaped_name}"}, node
        )

    for name in (
        "desc_addname",
        "desc_inline",
        "desc_name",
        "desc_returns",
        "desc_optional",
        "desc_sig_element",
        "desc_sig_keyword",
        "desc_sig_keyword_type",
        "desc_sig_literal_char",
        "desc_sig_literal_number",
        "desc_sig_literal_string",
        "desc_sig_name",
        "desc_signature_line",
        "desc_sig_operator",
        "desc_sig_punctuation",
        "desc_sig_space",
        "desc_type",
        "desc_type_parameter",
    ):
        locals()[f"visit_{name}"] = _visit_span


for name in (
    "attention",
    "caution",
    "danger",
    "error",
    "hint",
    "important",
    "note",
    "tip",
    "warning",
    "seealso",
):

    def visitor(self, node, name=name):
        return self.enter_myst_node(
            {"type": "admonition", "kind": name, "children": []}, node
        )

    setattr(MySTNodeVisitor, f"visit_{name}", visitor)
