from textual.binding import Binding
from textual.widgets import Input
from textual.widgets import Tree as TextualTree


class PageInput(Input):
    """An Input that sends Escape to the app so the app can hide us."""

    BINDINGS = [
        Binding("escape", "app.cancel_page_jump", "Cancel", show=False),
        Binding("ctrl+g", "app.cancel_page_jump", "Cancel", show=False),
    ]


class PDFTree(TextualTree):
    """A custom tree that supports Vim bindings and Left/Right expansion."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "collapse_node", "Collapse", show=False),
        Binding("l", "expand_node", "Expand", show=False),
        Binding("left", "collapse_node", "Collapse", show=False),
        Binding("right", "expand_node", "Expand", show=False),
    ]

    def action_collapse_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.select_node(node.parent)

    def action_expand_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if not node.is_expanded and node.allow_expand:
            node.expand()
        elif node.is_expanded and node.children:
            self.select_node(node.children[0])


class SearchInput(Input):
    """An Input that sends Escape to the app so the app can hide us."""

    BINDINGS = [
        Binding("escape", "app.cancel_search", "Cancel", show=False),
        Binding("ctrl+g", "app.cancel_search", "Cancel", show=False),
    ]
