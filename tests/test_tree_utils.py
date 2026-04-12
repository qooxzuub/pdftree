"""Unit tests for tree_utils.py — exercises iter_nodes, get_node_name,
get_node_by_path, and rebuild_stream_label inside a minimal Textual app."""

import pikepdf
import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Tree

from pdftree.pdf_utils import JumpReference, build_tree
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


# ---------------------------------------------------------------------------
# rebuild_stream_label
# ---------------------------------------------------------------------------


class TestRebuildStreamLabel:
    @pytest.mark.asyncio
    async def test_sets_name_and_stream_suffix(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)

        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

        rebuild_stream_label(stream_node)
        plain = stream_node.label.plain
        assert "Stream" in plain
        assert get_node_name(stream_node) in plain

    @pytest.mark.asyncio
    async def test_appends_byte_count(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)

        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

        rebuild_stream_label(stream_node, new_length=1234)
        assert "1234" in stream_node.label.plain

    @pytest.mark.asyncio
    async def test_no_length_when_none(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)

        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

        rebuild_stream_label(stream_node, new_length=None)
        # Should not contain any digit string that looks like a byte count
        plain = stream_node.label.plain
        # The objgen numbers will still be there, but no standalone "bytes"
        assert "bytes" not in plain

    @pytest.mark.asyncio
    async def test_preserves_objgen_annotation(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)

        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_node = next(n for n in all_nodes if isinstance(n.data, pikepdf.Stream))

        rebuild_stream_label(stream_node, new_length=42)
        plain = stream_node.label.plain
        # Indirect object should still show Obj N:M
        assert "Obj" in plain


# ---------------------------------------------------------------------------
# build_tree structure
# ---------------------------------------------------------------------------


class TestBuildTree:
    @pytest.mark.asyncio
    async def test_single_page_has_stream_node(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
        assert len(stream_nodes) >= 1

    @pytest.mark.asyncio
    async def test_stream_node_named_contents(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
        names = [get_node_name(n) for n in stream_nodes]
        assert "/Contents" in names

    @pytest.mark.asyncio
    async def test_registry_maps_objgen_to_node(self, tree_app, simple_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        # Every indirect object should be in the registry
        assert len(registry) > 0
        for objgen, node in registry.items():
            assert isinstance(objgen, tuple)
            assert len(objgen) == 2

    @pytest.mark.asyncio
    async def test_jump_reference_created_for_repeated_object(self, tree_app, simple_pdf):
        """/Parent back-references should become JumpReference nodes."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(simple_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        jump_nodes = [n for n in all_nodes if isinstance(n.data, JumpReference)]
        # /Parent on the page object refers back to /Pages, so at least one jump
        assert len(jump_nodes) >= 1

    @pytest.mark.asyncio
    async def test_multipage_contents_array_stream_nodes(self, tree_app, multipage_pdf):
        """Each page has 2 content streams via a /Contents Array — 6 total."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(multipage_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
        assert len(stream_nodes) == 6

    @pytest.mark.asyncio
    async def test_multipage_contents_array_parent_names(self, tree_app, multipage_pdf):
        """Array element streams should have /Contents as parent name."""
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(multipage_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]

        for node in stream_nodes:
            parent_name = get_node_name(node.parent) if node.parent else ""
            # Each stream is either named /Contents directly or is a child of /Contents
            node_n = get_node_name(node)
            assert (
                node_n == "/Contents" or parent_name == "/Contents"
            ), f"Unexpected stream node: name={node_n}, parent={parent_name}"

    @pytest.mark.asyncio
    async def test_xobject_form_stream_present(self, tree_app, xobject_pdf):
        app, _ = tree_app
        tree = app.query_one("#tree", Tree)
        pdf = pikepdf.Pdf.open(xobject_pdf)
        registry = {}
        build_tree(pdf.trailer, tree.root, node_registry=registry, name="Trailer")

        all_nodes = list(iter_nodes(tree.root))
        stream_nodes = [n for n in all_nodes if isinstance(n.data, pikepdf.Stream)]
        # Verify Form and Image XObjects both appear as stream nodes
        assert len(stream_nodes) >= 2


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
