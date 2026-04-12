import cProfile
import io
import os
import pathlib
import pstats
import re
import shlex
import subprocess
import sys
import tempfile

import pikepdf
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, RichLog
from textual.widgets import Tree as TextualTree
from textual.widgets.tree import TreeNode

HELP_TEXT = """\
# Keybindings Explorer

| Key | Action |
| --- | --- |
| **F1** or **H** | Show/Hide this help menu |
| **/** | Search forward |
| **?** | Search backward |
| **n** / **p** | Repeat search forward / backward |
| **Esc** | Cancel search |
| **j** / **k** / **↓** / **↑** | Navigate tree vertically |
| **h** / **←** | Collapse node / Jump to parent |
| **l** / **→** | Expand node / Jump to first child |
| **g** | Go to page... |
| **s** | Save stream content... |
| **f** | Format/normalize stream content |
| **e** | Edit stream content |
| **w** | Write PDF file to disk |
| **Enter** | Follow link / Open stream |
| **Ctrl+Z** | Suspend process |
| **Ctrl+L** | Force screen redraw |
| **q** / **Ctrl+C** | Quit application |
"""


class UnsavedChangesScreen(ModalScreen[bool]):
    """A modal to confirm quitting with unsaved changes."""

    BINDINGS = [
        Binding("y", "quit_anyway", "Quit"),
        Binding("n", "cancel", "Cancel"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="unsaved-prompt-container"):
            yield Label(
                "You have unsaved changes!\n(Hit n w to save.)\n\nQuit anyway? (y/n)",
                id="unsaved-label",
            )

    def action_quit_anyway(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PromptScreen(ModalScreen[str | None]):
    """A generic modal screen that prompts for a filename."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, default_placeholder: str = ""):
        super().__init__()
        self.title_text = title
        self.default_placeholder = default_placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-container"):
            yield Label(self.title_text, id="prompt-label")
            yield Input(id="prompt-input")

    def on_mount(self) -> None:
        # Pre-fill the value so the user can just hit Enter if they like the default
        input_widget = self.query_one(Input)
        input_widget.value = self.default_placeholder
        input_widget.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        filename = event.value.strip()
        self.dismiss(filename if filename else None)


class PageInput(Input):
    """An Input that sends Escape to the app so the app can hide us."""

    BINDINGS = [
        Binding("escape", "app.cancel_page_jump", "Cancel", show=False),
    ]


class HelpScreen(ModalScreen):
    """A modal screen showing keybindings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Dismiss"),
        Binding("f1", "dismiss", "Dismiss"),
        Binding("q", "dismiss", "Dismiss"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield Markdown(HELP_TEXT)

    def action_dismiss(self) -> None:
        self.dismiss()


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
    ]


class JumpReference:
    """A safe wrapper to tell the UI that this node is a hyperlink to another node."""

    def __init__(self, target_node: TreeNode):
        self.target_node = target_node


def sort_pdf_keys(item):
    key, val = item
    str_key = str(key)
    if str_key == "/Type":
        priority = -1
    elif str_key in ("/Root", "/Pages", "/Kids"):
        priority = 0
    elif isinstance(val, (pikepdf.Dictionary, pikepdf.Array, pikepdf.Stream)):
        priority = 2
    else:
        priority = 1
    return (priority, str_key)


def build_tree(pdf_root, tree_root: TreeNode, node_registry=None, name="Trailer"):
    if node_registry is None:
        node_registry = {}

    # Stack items: (pdf_obj, parent_tree_node, name)
    stack = [(pdf_root, tree_root, name)]

    while stack:
        pdf_obj, parent_node, current_name = stack.pop()

        obj_label_text = ""
        is_ind = getattr(pdf_obj, "is_indirect", False)

        label = Text()

        if is_ind:
            if pdf_obj.objgen in node_registry:
                label.append(
                    f"{current_name}: ↪ Jump to Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}",
                    style="dim underline italic",
                )
                parent_node.add_leaf(
                    label, data=JumpReference(node_registry[pdf_obj.objgen])
                )
                continue
            obj_label_text = f"(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})"

        if isinstance(pdf_obj, pikepdf.Dictionary):
            label.append(current_name, style="bold blue")
            if obj_label_text:  # the "(Obj N:M)" part
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(f" Dict[{len(pdf_obj)}]", style="dim")
            new_node = parent_node.add(label, data=pdf_obj)

            if is_ind:
                node_registry[pdf_obj.objgen] = new_node
            # Push children in reverse so they're processed in original order
            for key, val in sorted(pdf_obj.items(), key=sort_pdf_keys, reverse=True):
                stack.append((val, new_node, str(key)))

        elif isinstance(pdf_obj, pikepdf.Array):
            label.append(current_name, style="bold green")
            if obj_label_text:
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(f" Array[{len(pdf_obj)}]", style="dim")

            new_node = parent_node.add(label, data=pdf_obj)
            for i, val in reversed(list(enumerate(pdf_obj))):
                stack.append((val, new_node, f"[{i}]"))

        elif isinstance(pdf_obj, pikepdf.Stream):
            label.append(current_name, style="bold red")
            if obj_label_text:
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(" Stream", style="dim")
            new_node = parent_node.add(label, data=pdf_obj)

            if is_ind:
                node_registry[pdf_obj.objgen] = new_node
            for key, val in sorted(pdf_obj.items(), key=sort_pdf_keys, reverse=True):
                stack.append((val, new_node, str(key)))

        else:
            val_str = str(pdf_obj)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            label.append(current_name, style="bold cyan")
            if is_ind:
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(f": {val_str}")
            new_node = parent_node.add_leaf(label, data=pdf_obj)
            if is_ind:
                node_registry[pdf_obj.objgen] = new_node


def _iter_nodes(root: TreeNode):
    """Iterative pre-order traversal — avoids recursion-limit issues on deep trees."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        # Push children in reverse so left-most child is processed first
        for child in reversed(node.children):
            stack.append(child)


class PDFTreeApp(App):
    """A Textual app to interactively explore PDF structures and view stream contents."""

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
        Binding("H", "show_help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("g", "prompt_page", "Go to Page (g)", show=True),
        Binding("s", "export_stream", "Save stream (s)", show=True),
        Binding("e", "edit_stream", "Edit Stream (e)", show=True),
        Binding("f", "normalize_stream", "Format Stream (f)", show=True),
        Binding("w", "save_pdf", "Save PDF (w)", show=True),
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+z", "suspend_process", "Suspend", show=True),
        Binding("ctrl+l", "redraw_screen", "Redraw", show=False),
        Binding("/", "search_forward", "Search (/)", show=True),
        Binding("?", "search_backward", "Search (?)", show=True),
        Binding("n", "repeat_search_forward", "Next (n)", show=True),
        Binding("p", "repeat_search_backward", "Prev (p)", show=True),
    ]

    TITLE = "pdftree - Interactive Object Explorer"

    CSS = """
    #tree-pane {
        width: 1fr;
        height: 100%;
        border-right: solid $primary;
        padding: 1;
    }
    #right-pane {
        width: 1fr;
        height: 100%;
    }
    #breadcrumb {
        width: 100%;
        background: $boost;
        padding: 1 2;
        text-style: bold;
        border-bottom: solid $primary;
    }
    #details-pane {
        width: 100%;
        height: 1fr;
        padding: 1;
        background: $surface;
    }
    #search-bar, #page-input {
        dock: bottom;
    }
    HelpScreen {
        align: center middle;
        background: $background 50%;
    }
    #help-container {
        width: 70;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }
    PromptScreen {
        align: center middle;
        background: $background 50%;
    }
    #prompt-container {
        width: 50;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }
    #prompt-label {
        padding-bottom: 1;
        text-style: bold;
    }
    UnsavedChangesScreen {
        align: center middle;
        background: $background 50%;
    }
    #unsaved-prompt-container {
        width: 40;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $error;
    }
    #unsaved-label {
        text-align: center;
        text-style: bold;
        color: $error;
    }
    """

    def __init__(self, pdf_path: str):
        super().__init__()
        self.pdf_path = pdf_path
        self.pdf = None
        self.last_search_query: str | None = None
        self._search_direction: str = "forward"
        # Flag to suppress on_tree_node_selected firing when we move the cursor
        # programmatically (search / jump). Stored on self, not on tree nodes.
        self._programmatic_move: bool = False
        self.obj_to_node: dict[tuple[int, int], TreeNode] = {}
        self.is_dirty: bool = False

    # -------------------------------------------------------------------------
    # Normalize stream
    # -------------------------------------------------------------------------

    def node_name(self, node):
        label_str = (
            node.label.plain if hasattr(node.label, "plain") else str(node.label)
        )
        return label_str.split()[0]

    def action_normalize_stream(self) -> None:
        """Format a content stream to have one operator per line."""
        tree = self.query_one("#tree-pane", TextualTree)
        node = tree.cursor_node

        if node is None or not isinstance(node.data, pikepdf.Stream):
            self.query_one("#breadcrumb", Label).update(
                "[yellow]Please select a Stream node (Red) to format.[/yellow]"
            )
            return

        node_name = self.node_name(node)
        parent_name = self.node_name(node.parent) if node.parent is not None else ""

        if not is_content_stream(node.data, node_name, parent_name):
            self.query_one("#breadcrumb", Label).update(
                (
                    f"[yellow]Not reformatting '{node_name}' (parent: '{parent_name}') as it is not a content stream.[/yellow]"
                )
            )
            return

        try:
            # 1. Parse and unparse using pikepdf
            parsed = pikepdf.parse_content_stream(node.data)
            normalized_bytes = pikepdf.unparse_content_stream(parsed)

            # 2. Check if it actually changed
            old_bytes = node.data.read_bytes()
            if normalized_bytes != old_bytes:
                # 3. Write back to pikepdf
                node.data.write(normalized_bytes)

                # 4. Update the label length safely
                self._rebuild_stream_label(node, len(normalized_bytes))

                self.is_dirty = True

                self.query_one("#breadcrumb", Label).update(
                    f"[green]Stream formatted! Length: {len(old_bytes)} -> {len(normalized_bytes)} bytes.[/green]"
                )

                # Force a redraw of the detail pane to show the formatted text
                def do_refresh():
                    self._programmatic_move = True
                    tree.select_node(node)

                self.call_after_refresh(do_refresh)

            else:
                self.query_one("#breadcrumb", Label).update(
                    "[dim]Stream already formatted or unchanged.[/dim]"
                )

        except Exception as e:
            # This will catch if the user tries to format an image stream or
            # something else that isn't a valid PDF content stream.
            self.query_one("#breadcrumb", Label).update(
                f"[red]Failed to format (might not be a content stream):[/red] {e}"
            )

    # -------------------------------------------------------------------------
    # Prompt for save on quit
    # -------------------------------------------------------------------------

    def action_quit(self) -> None:
        """Override Textual's default quit to check for unsaved changes."""
        if getattr(self, "is_dirty", False):
            # Prompt the user if changes exist
            self.push_screen(UnsavedChangesScreen(), self._quit_confirm_callback)
        else:
            # Otherwise, use Textual's native exit method
            self.exit()

    def _quit_confirm_callback(self, quit_anyway: bool) -> None:
        """Callback fired when the UnsavedChangesScreen is dismissed."""
        if quit_anyway:
            self.exit()

    # -------------------------------------------------------------------------
    # Screen helpers
    # -------------------------------------------------------------------------

    def action_redraw_screen(self, *args, **kwargs) -> None:
        self.screen.refresh(layout=True)

    # -------------------------------------------------------------------------
    # Page navigation
    # -------------------------------------------------------------------------

    def action_prompt_page(self) -> None:
        """Open the page jump prompt."""
        page_input = self.query_one("#page-input", PageInput)
        page_input.value = ""
        page_input.display = True
        page_input.focus()

    def action_cancel_page_jump(self) -> None:
        """Hide the page jump prompt."""
        page_input = self.query_one("#page-input", PageInput)
        page_input.display = False
        self.query_one("#tree-pane").focus()

    # -------------------------------------------------------------------------
    # Export stream
    # -------------------------------------------------------------------------

    def _save_stream_callback(self, filename: str | None) -> None:
        """Callback fired when the SavePromptScreen is dismissed."""
        if not filename:
            return  # User canceled or entered an empty string

        node = getattr(self, "_pending_export_node", None)

        # Double check we are still on a stream just in case
        if node is None or not isinstance(node.data, pikepdf.Stream):
            return

        try:
            raw_bytes = node.data.read_bytes()
            with open(filename, "wb") as f:
                f.write(raw_bytes)

            self.query_one("#breadcrumb", Label).update(
                f"[green]Successfully saved {len(raw_bytes)} bytes to '{filename}'[/green]"
            )
        except Exception as e:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Failed to save file:[/red] {e}"
            )

    # -------------------------------------------------------------------------
    # Edit stream
    # -------------------------------------------------------------------------

    def action_edit_stream(self) -> None:
        """Export stream to temp file, suspend TUI, run $EDITOR, read back."""
        tree = self.query_one("#tree-pane", PDFTree)
        node = tree.cursor_node

        if node is None or not isinstance(node.data, pikepdf.Stream):
            self.query_one("#breadcrumb", Label).update(
                "[yellow]Please select a Stream node (Red) to edit.[/yellow]"
            )
            return

        # 1. Setup temp file
        try:
            old_bytes = node.data.read_bytes()
            fd, temp_path = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "wb") as f:
                f.write(old_bytes)
        except Exception as e:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Error reading stream:[/red] {e}"
            )
            return

        editor_env = os.environ.get("EDITOR", "nano" if os.name != "nt" else "notepad")
        cmd_list = shlex.split(editor_env) + [temp_path]

        # 2. Safely call the editor
        try:
            with self.suspend():
                subprocess.run(cmd_list, check=True)
        except FileNotFoundError:
            os.remove(temp_path)
            self.query_one("#breadcrumb", Label).update(
                f"[red]Editor not found:[/red] '{cmd_list[0]}'. Check your $EDITOR variable."
            )
            return
        except subprocess.CalledProcessError as e:
            os.remove(temp_path)
            self.query_one("#breadcrumb", Label).update(
                f"[red]Editor exited with an error code:[/red] {e.returncode}"
            )
            return

        # 3. Process the results
        try:
            with open(temp_path, "rb") as f:
                new_bytes = f.read()
            os.remove(temp_path)

            if new_bytes != old_bytes:
                # Write back to pikepdf
                node.data.write(new_bytes)

                self._rebuild_stream_label(node, len(new_bytes))

                # Set dirty flag *after* successful write
                self.is_dirty = True

                self.query_one("#breadcrumb", Label).update(
                    f"[green]Stream updated! Length changed: {len(old_bytes)} -> {len(new_bytes)} bytes.[/green]"
                )
                self.call_after_refresh(lambda: tree.select_node(node))
            else:
                self.query_one("#breadcrumb", Label).update(
                    "[dim]Stream unchanged. Editing canceled.[/dim]"
                )
        except Exception as e:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Error saving stream data:[/red] {e}"
            )

    def _rebuild_stream_label(self, node: TreeNode, new_length: int) -> None:
        """Reconstruct a stream node's Text label with an updated byte count."""
        # node.label.plain looks like "/Contents (Obj 5:0) Stream"
        # We have all the info we need in node.data
        stream = node.data
        name = self.node_name(node)
        is_ind = getattr(stream, "is_indirect", False)

        label = Text()
        label.append(name, style="bold red")
        if is_ind:
            label.append(
                f" (Obj {stream.objgen[0]}:{stream.objgen[1]})", style="dim yellow"
            )
        label.append(" Stream", style="dim")
        node.set_label(label)

    # -------------------------------------------------------------------------
    # Save PDF
    # -------------------------------------------------------------------------

    def action_save_pdf(self) -> None:
        """Prompt the user for a filename to save the entire document."""
        p = pathlib.Path(self.pdf_path)
        default_name = f"{p.stem}_modified{p.suffix}"

        self.push_screen(
            PromptScreen("Save Entire PDF As:", default_name), self._save_pdf_callback
        )

    def action_export_stream(self) -> None:
        """Prompt to save the currently selected stream."""
        tree = self.query_one("#tree-pane", PDFTree)
        node = tree.cursor_node

        if node is not None and isinstance(node.data, pikepdf.Stream):
            self._pending_export_node = node
            self.push_screen(
                PromptScreen("Export Stream As:", "stream.bin"),
                self._save_stream_callback,
            )
        else:
            self.query_one("#breadcrumb", Label).update(
                "[yellow]Please select a Stream node (Red) to export.[/yellow]"
            )

    def _save_pdf_callback(self, filename: str | None) -> None:
        if not filename:
            return

        try:
            # Dump the in-memory pikepdf object tree back out to disk
            self.pdf.save(filename)
            self.is_dirty = False

            self.query_one("#breadcrumb", Label).update(
                f"[green]Successfully saved modified PDF to '{filename}'[/green]"
            )
        except Exception as e:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Failed to save PDF:[/red] {e}"
            )

    # -------------------------------------------------------------------------
    # Help
    # -------------------------------------------------------------------------

    def action_show_help(self) -> None:
        """Push the help screen when the user presses a help key."""
        self.push_screen(HelpScreen())

    # -------------------------------------------------------------------------
    # Search actions
    # -------------------------------------------------------------------------

    def action_search_forward(self) -> None:
        self._search_direction = "forward"
        self._open_search_bar("forward (/)")

    def action_search_backward(self) -> None:
        self._search_direction = "backward"
        self._open_search_bar("backward (?)")

    def action_repeat_search_forward(self) -> None:
        self._search_direction = "forward"
        self._perform_search(self.last_search_query)

    def action_repeat_search_backward(self) -> None:
        self._search_direction = "backward"
        self._perform_search(self.last_search_query)

    def action_cancel_search(self) -> None:
        search_bar = self.query_one("#search-bar", SearchInput)
        search_bar.display = False
        search_bar.value = ""
        self.query_one("#tree-pane").focus()

    def _open_search_bar(self, direction_text: str) -> None:
        search_bar = self.query_one("#search-bar", SearchInput)
        search_bar.placeholder = (
            f"Search {direction_text}  —  Enter to jump · Esc to cancel"
        )
        search_bar.display = True
        search_bar.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.display = False
        self.query_one("#tree-pane").focus()

        if event.input.id == "search-bar":
            query = event.value.strip().lower()
            if query:
                self.last_search_query = query
            self._perform_search(self.last_search_query)

        elif event.input.id == "page-input":
            self._handle_page_jump(event.value.strip())

    def _handle_page_jump(self, value: str) -> None:
        if not value:
            return

        try:
            page_num = int(value)
            num_pages = len(self.pdf.pages)
        except ValueError:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Invalid page number:[/red] {value}"
            )
            return

        if not (1 <= page_num <= num_pages):
            self.query_one("#breadcrumb", Label).update(
                f"[red]Page {page_num} out of bounds (1-{num_pages})[/red]"
            )
            return

        # 1. pikepdf gives us the canonical page dictionary via the flat .pages list
        page_obj = self.pdf.pages[page_num - 1]

        # 2. Extract its exact object/generation signature
        target_node = self.obj_to_node.get(page_obj.objgen)

        if target_node:
            self._expand_to(target_node)

            tree = self.query_one("#tree-pane", PDFTree)

            def do_jump():
                self._programmatic_move = True
                tree.select_node(target_node)

            self.call_after_refresh(do_jump)

            self.query_one("#breadcrumb", Label).update(
                f"[green]Jumped to Page {page_num} ({page_obj.objgen[0]}:{page_obj.objgen[1]})[/green]"
            )
        else:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Could not find tree node for Page {page_num}[/red]"
            )

    def _perform_search(self, query: str | None) -> None:
        if not query:
            return

        tree = self.query_one("#tree-pane", PDFTree)
        tree.focus()

        all_nodes = list(_iter_nodes(tree.root))

        start_node = tree.cursor_node
        try:
            start_idx = all_nodes.index(start_node)
        except ValueError:
            start_idx = -1

        if self._search_direction == "forward":
            if start_idx == -1:
                search_sequence = all_nodes
            else:
                search_sequence = (
                    all_nodes[start_idx + 1 :] + all_nodes[: start_idx + 1]
                )
        else:
            if start_idx == -1:
                search_sequence = all_nodes[::-1]
            else:
                search_sequence = (
                    all_nodes[:start_idx][::-1] + all_nodes[start_idx:][::-1]
                )

        match = next(
            (n for n in search_sequence if query in n.label.plain.lower()), None
        )

        if match:
            self._expand_to(match)

            def do_jump():
                self._programmatic_move = True
                tree.select_node(match)

            self.call_after_refresh(do_jump)

            status = f"[green]Found:[/green] {query}"
        else:
            status = f"[red]Not found:[/red] {query}"

        self.query_one("#breadcrumb", Label).update(status)

    # -------------------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield PDFTree(
                f"[bold magenta]{self.pdf_path}[/bold magenta]", id="tree-pane"
            )
            with Vertical(id="right-pane"):
                yield Label("Trailer", id="breadcrumb")
                yield RichLog(
                    id="details-pane", highlight=True, wrap=True, auto_scroll=False
                )
        yield SearchInput(
            placeholder="Search nodes (Enter to jump, Esc to cancel)...",
            id="search-bar",
        )
        yield PageInput(
            placeholder="Go to page (Enter to jump, Esc to cancel)...",
            id="page-input",
        )

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def on_mount(self) -> None:
        tree = self.query_one("#tree-pane", PDFTree)
        log = self.query_one("#details-pane", RichLog)

        tree.auto_expand = False
        tree.root.expand()
        log.write(
            Text.from_markup(
                "[dim italic]Select a Stream node (Red) to view contents, "
                "or click a ↪ Jump link to navigate.[/dim italic]"
            )
        )

        self.app_resume_signal.subscribe(self, self.action_redraw_screen)
        self.query_one("#search-bar").display = False
        self.query_one("#page-input").display = False

        pr = cProfile.Profile()
        pr.enable()

        try:
            self.pdf = pikepdf.Pdf.open(self.pdf_path)
            with self.app.batch_update():
                build_tree(
                    self.pdf.trailer,
                    tree.root,
                    node_registry=self.obj_to_node,
                    name="Trailer",
                )
        except Exception as e:
            tree.root.add_leaf(f"[bold red]Fatal Error opening PDF: {e}[/bold red]")

        pr.disable()

        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
        ps.print_stats(20)  # top 20 calls

        # Write to file so it doesn't get swallowed by the TUI
        with open("profile_report.txt", "w") as f:
            f.write(s.getvalue())

        self._startup_selection(tree)

    def on_unmount(self) -> None:
        if self.pdf:
            self.pdf.close()

    # -------------------------------------------------------------------------
    # Tree events
    # -------------------------------------------------------------------------

    def on_tree_node_highlighted(self, event: TextualTree.NodeHighlighted) -> None:
        if event.node is None:
            return
        # Don't overwrite a search status message with the breadcrumb
        if self._programmatic_move:
            self._programmatic_move = False
            return

        parts = []
        curr = event.node
        while curr is not None and curr.parent is not None:
            parts.append(self.node_name(curr))
            curr = curr.parent
        parts.reverse()
        self.query_one("#breadcrumb", Label).update(" > ".join(parts))

    def on_tree_node_selected(self, event: TextualTree.NodeSelected) -> None:
        log = self.query_one("#details-pane", RichLog)
        tree = self.query_one("#tree-pane", TextualTree)
        node_data = event.node.data

        if not isinstance(node_data, (JumpReference, pikepdf.Stream)):
            return

        log.clear()
        log.scroll_home(animate=False)

        if isinstance(node_data, JumpReference):
            target = node_data.target_node
            if target:
                self._expand_to(target)
                self._programmatic_move = True
                self.call_after_refresh(lambda: tree.select_node(target))
                log.write(
                    Text.from_markup(
                        "[bold yellow]--- Jumped to Object ---[/bold yellow]"
                    )
                )
                log.write(
                    Text.from_markup(
                        "[dim]Moved cursor to the original location of this object.[/dim]"
                    )
                )
            return

        if isinstance(node_data, pikepdf.Stream):
            objgen_str = ":".join(str(x) for x in node_data.objgen)
            log.write(
                Text.from_markup(
                    f"[bold magenta]--- Obj {objgen_str} Decompressed Stream Output ---[/bold magenta]\n"
                )
            )
            try:
                raw_bytes = node_data.read_bytes()
                try:
                    log.write(raw_bytes.decode("utf-8"))
                except UnicodeDecodeError:
                    log.write(
                        Text.from_markup(
                            f"[bold red]<Binary Stream: {len(raw_bytes)} bytes>[/bold red]"
                        )
                    )
                    log.write(Text.from_markup("[dim]First 500 bytes as repr:[/dim]\n"))
                    log.write(repr(raw_bytes[:500]))
            except Exception as e:
                log.write(
                    Text.from_markup(f"[bold red]Error reading stream:[/bold red] {e}")
                )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _expand_to(self, node: TreeNode) -> None:
        """Expand all ancestors so a node is visible in the tree."""
        curr = node.parent
        while curr is not None:
            curr.expand()
            curr = curr.parent

    def _startup_selection(self, tree: PDFTree) -> None:
        pages_node = self._get_node_by_path(tree, ["Trailer", "/Root", "/Pages"])
        if pages_node:
            self._expand_to(pages_node)
            pages_node.expand()
            self.call_after_refresh(lambda: tree.select_node(pages_node))
            tree.focus()

    def _get_node_by_path(
        self, tree: PDFTree, path_steps: list[str]
    ) -> TreeNode | None:
        current_node = tree.root
        for step in path_steps:
            found = False
            for child in current_node.children:
                if step in child.label.plain:
                    current_node = child
                    found = True
                    break
            if not found:
                return None
        return current_node


def is_content_stream(stream: pikepdf.Stream, name: str, parent_name: str = "") -> bool:
    # Fast exit: image codecs mean raw pixel data
    image_filters = {"/DCTDecode", "/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode"}
    filters = stream.get("/Filter")
    if filters is not None:
        filter_list = (
            [str(filters)]
            if not isinstance(filters, pikepdf.Array)
            else [str(f) for f in filters]
        )
        if any(f in image_filters for f in filter_list):
            return False

    obj_type = str(stream.get("/Type", ""))
    obj_subtype = str(stream.get("/Subtype", ""))

    if name == "/Contents" or parent_name == "/Contents":
        return True
    if obj_type == "/Pattern":  # PatternType 1 tiling patterns
        return True
    if obj_type == "/XObject" and obj_subtype == "/Form":
        return True
    # Appearance streams have no /Type but are content streams
    if name in ("/N", "/R", "/D") and obj_type == "":
        return True  # heuristic — could false-positive on other anonymous streams

    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python tree_tui.py <file.pdf>")
        sys.exit(1)

    app = PDFTreeApp(sys.argv[1])
    app.run()

    # Force the terminal prompt below the leftover TUI ghost
    print("\033[999;1H\n", end="")

if __name__ == "__main__":
    main()
