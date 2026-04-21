"""Unit tests for tree_utils.py — exercises iter_nodes, get_node_name,
get_node_by_path, and rebuild_stream_label inside a minimal Textual app."""

import pikepdf
import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Tree

from pdftree.pdf_utils import JumpReference
from pdftree.tree_utils import (
    expand_to,
    get_node_by_path,
    get_node_name,
    iter_nodes,
    rebuild_stream_label,
)

# ---------------------------------------------------------------------------
# Minimal app fixture — gives us a real Tree widget to work with
# ---------------------------------------------------------------------------


class TreeApp(App):
    """Bare-minimum app that exposes a single Tree widget."""

    def compose(self) -> ComposeResult:
        yield Tree("root", id="tree")


@pytest.fixture
async def tree_app():
    """Run TreeApp headlessly and yield (app, pilot)."""
    app = TreeApp()
    async with app.run_test(headless=True) as pilot:
        yield app, pilot


# ---------------------------------------------------------------------------
# iter_nodes
# ---------------------------------------------------------------------------


class TestIterNodes:
    @pytest.mark.asyncio
    async def test_visits_root(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        nodes = list(iter_nodes(tree.root))
        assert tree.root in nodes

    @pytest.mark.asyncio
    async def test_visits_all_children(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        a = tree.root.add("A")
        b = tree.root.add("B")
        c = a.add("C")
        nodes = list(iter_nodes(tree.root))
        assert a in nodes
        assert b in nodes
        assert c in nodes

    @pytest.mark.asyncio
    async def test_preorder(self, tree_app):
        """Parent must appear before its children."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        parent = tree.root.add("parent")
        child = parent.add("child")
        nodes = list(iter_nodes(tree.root))
        assert nodes.index(parent) < nodes.index(child)

    @pytest.mark.asyncio
    async def test_leaf_nodes_included(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        leaf = tree.root.add_leaf("leaf")
        nodes = list(iter_nodes(tree.root))
        assert leaf in nodes

    @pytest.mark.asyncio
    async def test_empty_tree(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        nodes = list(iter_nodes(tree.root))
        # Just the root
        assert nodes == [tree.root]


# ---------------------------------------------------------------------------
# get_node_name
# ---------------------------------------------------------------------------


class TestGetNodeName:
    @pytest.mark.asyncio
    async def test_plain_string_label(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        node = tree.root.add("/Contents")
        assert get_node_name(node) == "/Contents"

    @pytest.mark.asyncio
    async def test_rich_text_label(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        label = Text()
        label.append("/Type", style="bold blue")
        label.append(" Dict[3]", style="dim")
        node = tree.root.add(label)
        assert get_node_name(node) == "/Type"

    @pytest.mark.asyncio
    async def test_label_with_objgen(self, tree_app):
        """Labels like '/Contents (Obj 4:0) Stream' should return '/Contents'."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        label = Text()
        label.append("/Contents", style="bold red")
        label.append(" (Obj 4:0)", style="dim yellow")
        label.append(" Stream", style="dim")
        node = tree.root.add(label)
        assert get_node_name(node) == "/Contents"

    @pytest.mark.asyncio
    async def test_array_element_label(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        label = Text()
        label.append("[0]", style="bold green")
        label.append(" Stream", style="dim")
        node = tree.root.add(label)
        assert get_node_name(node) == "[0]"


# ---------------------------------------------------------------------------
# get_node_by_path
# ---------------------------------------------------------------------------


class TestGetNodeByPath:
    @pytest.mark.asyncio
    async def test_finds_direct_child(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        child = tree.root.add("Trailer")
        result = get_node_by_path(tree, ["Trailer"])
        assert result is child

    @pytest.mark.asyncio
    async def test_finds_nested_path(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        trailer = tree.root.add("Trailer")
        root_node = trailer.add("/Root")
        pages = root_node.add("/Pages")
        result = get_node_by_path(tree, ["Trailer", "/Root", "/Pages"])
        assert result is pages

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_step(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        tree.root.add("Trailer")
        result = get_node_by_path(tree, ["Trailer", "/NonExistent"])
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_label_match(self, tree_app):
        """get_node_by_path uses 'in' so '/Root' matches '/Root (Obj 1:0) Dict[2]'."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        trailer = tree.root.add("Trailer")
        root_node = trailer.add("/Root (Obj 1:0) Dict[2]")
        result = get_node_by_path(tree, ["Trailer", "/Root"])
        assert result is root_node

    @pytest.mark.asyncio
    async def test_empty_path_returns_root(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        result = get_node_by_path(tree, [])
        assert result is tree.root


# # ---------------------------------------------------------------------------
# # rebuild_stream_label
# # ---------------------------------------------------------------------------


# class TestRebuildStreamLabel:
#     @pytest.mark.asyncio
#     async def test_sets_name_and_stream_suffix(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)

#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

#         rebuild_stream_label(stream_node)
#         plain = stream_node.label.plain
#         assert "Stream" in plain
#         assert get_node_name(stream_node) in plain

#     @pytest.mark.asyncio
#     async def test_appends_byte_count(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)

#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

#         rebuild_stream_label(stream_node, new_length=1234)
#         assert "1234" in stream_node.label.plain

#     @pytest.mark.asyncio
#     async def test_no_length_when_none(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)

#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

#         rebuild_stream_label(stream_node, new_length=None)
#         # Should not contain any digit string that looks like a byte count
#         plain = stream_node.label.plain
#         # The objgen numbers will still be there, but no standalone "bytes"
#         assert "bytes" not in plain

#     @pytest.mark.asyncio
#     async def test_preserves_objgen_annotation(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)

#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

#         rebuild_stream_label(stream_node, new_length=42)
#         plain = stream_node.label.plain
#         # Indirect object should still show Obj N:M
#         assert "Obj" in plain


# # ---------------------------------------------------------------------------
# # build_tree structure
# # ---------------------------------------------------------------------------


# class TestBuildTree:
#     @pytest.mark.asyncio
#     async def test_single_page_has_stream_node(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
#         assert len(stream_nodes) >= 1

#     @pytest.mark.asyncio
#     async def test_stream_node_named_contents(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
#         names = [get_node_name(n) for n in stream_nodes]
#         assert "/Contents" in names

#     @pytest.mark.asyncio
#     async def test_registry_maps_objgen_to_node(self, tree_app, simple_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         # Every indirect object should be in the registry
#         assert len(registry) > 0
#         for objgen, node in registry.items():
#             assert isinstance(objgen, tuple)
#             assert len(objgen) == 2

#     @pytest.mark.asyncio
#     async def test_jump_reference_created_for_repeated_object(
#         self, tree_app, simple_pdf
#     ):
#         """/Parent back-references should become JumpReference nodes."""
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(simple_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         jump_nodes = [n for n in all_nodes if isinstance(n.data, JumpReference)]
#         # /Parent on the page object refers back to /Pages, so at least one jump
#         assert len(jump_nodes) >= 1

#     @pytest.mark.asyncio
#     async def test_multipage_contents_array_stream_nodes(self, tree_app, multipage_pdf):
#         """Each page has 2 content streams via a /Contents Array — 6 total."""
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(multipage_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
#         assert len(stream_nodes) == 6

#     @pytest.mark.asyncio
#     async def test_multipage_contents_array_parent_names(self, tree_app, multipage_pdf):
#         """Array element streams should have /Contents as parent name."""
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(multipage_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]

#         for node in stream_nodes:
#             parent_name = get_node_name(node.parent) if node.parent else ""
#             # Each stream is either named /Contents directly or is a child of /Contents
#             node_n = get_node_name(node)
#             assert node_n == "/Contents" or parent_name == "/Contents", (
#                 f"Unexpected stream node: name={node_n}, parent={parent_name}"
#             )

#     @pytest.mark.asyncio
#     async def test_xobject_form_stream_present(self, tree_app, xobject_pdf):
#         app, _ = tree_app
#         tree = app.query_one("#tree", Tree)
#         pdf = pikepdf.Pdf.open(xobject_pdf)
#         registry = {}
#         build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

#         all_nodes = list(iter_nodes(tree.root))
#         stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
#         # Verify Form and Image XObjects both appear as stream nodes
#         assert len(stream_nodes) >= 2


# ---------------------------------------------------------------------------
# expand_to
# ---------------------------------------------------------------------------


class TestExpandTo:
    @pytest.mark.asyncio
    async def test_expand_ancestors(self, tree_app):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        a = tree.root.add("A")
        b = a.add("B")
        c = b.add("C")

        # Collapse everything first
        a.collapse()
        b.collapse()

        expand_to(c)

        assert a.is_expanded
        assert b.is_expanded

    @pytest.mark.asyncio
    async def test_expand_to_root_child(self, tree_app):
        """expand_to on a direct root child should not raise."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        child = tree.root.add("child")
        expand_to(child)  # parent is root — should just work silently


import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from rich.text import Text


# ---------------------------------------------------------------------------
# Helpers to build fake TreeNode objects without a running Textual app
# ---------------------------------------------------------------------------


def make_node(label_str, data=None, children=None, parent=None):
    """Build a minimal mock TreeNode."""
    node = MagicMock()
    label = Text(label_str)
    node.label = label
    node.data = data
    node.parent = parent
    node.children = children or []
    return node


def make_tree(label_str, children=None):
    """Build a small tree and wire up parent references."""
    root = make_node(label_str)
    root.parent = None
    root.children = []
    for child_label in children or []:
        child = make_node(child_label, parent=root)
        child.children = []
        root.children.append(child)
    return root


# ---------------------------------------------------------------------------
# expand_to
# ---------------------------------------------------------------------------


class TestExpandTo:
    def test_expands_all_ancestors(self):
        from pdftree.tree_utils import expand_to

        grandparent = make_node("root")
        grandparent.parent = None
        parent = make_node("parent", parent=grandparent)
        child = make_node("child", parent=parent)

        expand_to(child)

        parent.expand.assert_called_once()
        grandparent.expand.assert_called_once()

    def test_root_node_does_not_expand_itself(self):
        """expand_to walks parents; a node with no parent triggers no expand."""
        from pdftree.tree_utils import expand_to

        root = make_node("root")
        root.parent = None
        expand_to(root)
        root.expand.assert_not_called()

    def test_single_level_deep(self):
        from pdftree.tree_utils import expand_to

        parent = make_node("parent")
        parent.parent = None
        child = make_node("child", parent=parent)

        expand_to(child)
        parent.expand.assert_called_once()


# ---------------------------------------------------------------------------
# get_node_name
# ---------------------------------------------------------------------------


class TestGetNodeName:
    def test_returns_first_word_of_plain_label(self):
        from pdftree.tree_utils import get_node_name

        node = make_node("/Font Dict[3]")
        assert get_node_name(node) == "/Font"

    def test_single_word_label(self):
        from pdftree.tree_utils import get_node_name

        node = make_node("Trailer")
        assert get_node_name(node) == "Trailer"

    def test_label_without_plain_attribute(self):
        """Falls back to str(label) when .plain is absent."""
        from pdftree.tree_utils import get_node_name

        node = MagicMock()
        del node.label.plain  # remove .plain
        node.label.__str__ = lambda self: "/Pages Array[2]"
        assert get_node_name(node) == "/Pages"


# ---------------------------------------------------------------------------
# get_node_by_path
# ---------------------------------------------------------------------------


class TestGetNodeByPath:
    def _build_tree(self):
        """
        root
        └── /Root Dict[1]
            └── /Pages Array[2]
        """
        root = make_node("Trailer")
        root.parent = None

        child1 = make_node("/Root Dict[1]", parent=root)
        grandchild = make_node("/Pages Array[2]", parent=child1)
        grandchild.children = []
        child1.children = [grandchild]
        root.children = [child1]

        tree = MagicMock()
        tree.root = root
        return tree

    def test_finds_existing_path(self):
        from pdftree.tree_utils import get_node_by_path

        tree = self._build_tree()
        node = get_node_by_path(tree, ["/Root", "/Pages"])
        assert node is not None
        assert "/Pages" in node.label.plain

    def test_returns_none_for_missing_step(self):
        from pdftree.tree_utils import get_node_by_path

        tree = self._build_tree()
        node = get_node_by_path(tree, ["/Root", "/Missing"])
        assert node is None

    def test_empty_path_returns_root(self):
        from pdftree.tree_utils import get_node_by_path

        tree = self._build_tree()
        node = get_node_by_path(tree, [])
        assert node is tree.root


# ---------------------------------------------------------------------------
# rebuild_stream_label
# ---------------------------------------------------------------------------


class TestRebuildStreamLabel:
    def _stream_node(self, name, is_indirect=False, objgen=(5, 0)):
        node = MagicMock()
        node.label = Text(f"{name} Stream")
        stream = MagicMock()
        stream.is_indirect = is_indirect
        stream.objgen = objgen
        node.data = stream
        return node

    def test_direct_stream_no_objgen(self):
        from pdftree.tree_utils import rebuild_stream_label

        node = self._stream_node("/Contents", is_indirect=False)
        rebuild_stream_label(node)

        label: Text = node.set_label.call_args[0][0]
        plain = label.plain
        assert "/Contents" in plain
        assert "Stream" in plain
        assert "Obj" not in plain

    def test_indirect_stream_includes_objgen(self):
        from pdftree.tree_utils import rebuild_stream_label

        node = self._stream_node("/Contents", is_indirect=True, objgen=(7, 0))
        rebuild_stream_label(node)

        label: Text = node.set_label.call_args[0][0]
        assert "7:0" in label.plain

    def test_new_length_appended(self):
        from pdftree.tree_utils import rebuild_stream_label

        node = self._stream_node("/Contents", is_indirect=False)
        rebuild_stream_label(node, new_length=1024)

        label: Text = node.set_label.call_args[0][0]
        assert "1024" in label.plain

    def test_no_length_when_none(self):
        from pdftree.tree_utils import rebuild_stream_label

        node = self._stream_node("/Contents", is_indirect=False)
        rebuild_stream_label(node, new_length=None)

        label: Text = node.set_label.call_args[0][0]
        assert "bytes" not in label.plain


# ---------------------------------------------------------------------------
# iter_nodes
# ---------------------------------------------------------------------------


class TestIterNodes:
    def test_yields_root(self):
        from pdftree.tree_utils import iter_nodes

        root = make_node("root")
        nodes = list(iter_nodes(root))
        assert root in nodes

    def test_pre_order_traversal(self):
        from pdftree.tree_utils import iter_nodes

        root = make_node("root")
        a = make_node("a")
        b = make_node("b")
        c = make_node("c")
        a.children = [c]
        root.children = [a, b]

        names = [n.label.plain for n in iter_nodes(root)]
        # pre-order: root before children, a before c, a before b
        assert names.index("root") < names.index("a")
        assert names.index("root") < names.index("b")
        assert names.index("a") < names.index("c")

    def test_yields_all_nodes(self):
        from pdftree.tree_utils import iter_nodes

        root = make_node("root")
        children = [make_node(str(i)) for i in range(5)]
        for c in children:
            c.children = []
        root.children = children

        all_nodes = list(iter_nodes(root))
        assert len(all_nodes) == 6  # root + 5 children

    def test_leaf_node(self):
        from pdftree.tree_utils import iter_nodes

        leaf = make_node("leaf")
        assert list(iter_nodes(leaf)) == [leaf]
