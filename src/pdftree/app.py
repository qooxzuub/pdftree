import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import signal

import pikepdf
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, RichLog
from textual.widgets import Tree as TextualTree
from textual.widgets.tree import TreeNode

from .pdf_utils import JumpReference, build_tree, is_content_stream
from .screens import HelpScreen, PromptScreen, UnsavedChangesScreen
from .tree_utils import (
    expand_to,
    get_node_by_path,
    get_node_name,
    iter_nodes,
    rebuild_stream_label,
)
from .widgets import PageInput, PDFTree, SearchInput


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
        Binding("x", "extract_image", "Extract image (x)", show=True),
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+z", "suspend_process", "Suspend", show=True),
        Binding("ctrl+l", "redraw_screen", "Redraw", show=False),
        Binding("/", "search_forward", "Search (/)", show=True),
        Binding("?", "search_backward", "Search (?)", show=True),
        Binding("n", "repeat_search_forward", "Next (n)", show=True),
        Binding("p", "repeat_search_backward", "Prev (p)", show=True),
    ]

    TITLE = "pdftree - Interactive Object Explorer"

    CSS_PATH = "styles.tcss"

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

    def action_suspend_process(self) -> None:
        with self.suspend():
            print("\033[999;1H\n", end="", flush=True)
            os.kill(os.getpid(), signal.SIGTSTP)  # SIGTSTP not SIGSTOP

    # -------------------------------------------------------------------------
    # Extract Image
    # -------------------------------------------------------------------------

    def action_extract_image(self) -> None:
        """Prompt to extract the currently selected image stream."""
        tree = self.query_one("#tree-pane", PDFTree)
        node = tree.cursor_node

        if node is None or not isinstance(node.data, pikepdf.Stream):
            self.query_one("#breadcrumb", Label).update(
                "[yellow]Please select a Stream node (Red) to extract.[/yellow]"
            )
            return

        # Ensure it is actually an image stream
        if node.data.get("/Subtype") != "/Image":
            self.query_one("#breadcrumb", Label).update(
                "[yellow]Selected stream is not an image (/Subtype is not /Image).[/yellow]"
            )
            return

        self._pending_export_node = node

        # We prompt for a prefix because pikepdf appends the correct extension automatically
        self.push_screen(
            PromptScreen("Image file prefix (extension added automatically):", "image_out"),
            self._extract_image_callback,
        )

    def _extract_image_callback(self, fileprefix: str | None) -> None:
        """Callback fired when the Extract Image PromptScreen is dismissed."""
        if not fileprefix:
            return  # User canceled or entered an empty string

        node = getattr(self, "_pending_export_node", None)
        if node is None or not isinstance(node.data, pikepdf.Stream):
            return

        try:
            from pikepdf.models import PdfImage

            # Wrap the stream in the PdfImage helper
            pdf_img = PdfImage(node.data)

            # extract_to saves the file and returns the actual path (e.g., 'image_out.jpg')
            saved_path = pdf_img.extract_to(fileprefix=fileprefix)

            self.query_one("#breadcrumb", Label).update(
                f"[green]Successfully extracted image to '{saved_path}'[/green]"
            )
        except ImportError:
            # pikepdf requires the Pillow library for advanced image manipulation
            self.query_one("#breadcrumb", Label).update(
                "[red]Pillow is required for image extraction. Run: pip install Pillow[/red]"
            )
        except Exception as e:
            self.query_one("#breadcrumb", Label).update(f"[red]Failed to extract image:[/red] {e}")

    # -------------------------------------------------------------------------
    # Normalize stream
    # -------------------------------------------------------------------------

    def action_normalize_stream(self) -> None:
        """Format a content stream to have one operator per line."""
        tree = self.query_one("#tree-pane", TextualTree)
        node = tree.cursor_node

        if node is None or not isinstance(node.data, pikepdf.Stream):
            self.query_one("#breadcrumb", Label).update(
                "[yellow]Please select a Stream node (Red) to format.[/yellow]"
            )
            return

        node_name = get_node_name(node)
        parent_name = get_node_name(node.parent) if node.parent is not None else ""

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
                rebuild_stream_label(node, len(normalized_bytes))

                self.is_dirty = True

                self.query_one("#breadcrumb", Label).update(
                    f"[green]Stream formatted! Length: {len(old_bytes)} -> {len(normalized_bytes)} bytes.[/green]"
                )

                # Force a redraw of the detail pane to show the formatted text
                self.call_after_refresh(self.do_jump_factory(tree, node))

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

    def do_jump_factory(self, tree, node):
        def jump():
            self._programmatic_move = True
            tree.select_node(node)

        return jump

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
            self.query_one("#breadcrumb", Label).update(f"[red]Failed to save file:[/red] {e}")

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
            self.query_one("#breadcrumb", Label).update(f"[red]Error reading stream:[/red] {e}")
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

                rebuild_stream_label(node, len(new_bytes))

                # Set dirty flag *after* successful write
                self.is_dirty = True

                self.query_one("#breadcrumb", Label).update(
                    f"[green]Stream updated! Length changed: {len(old_bytes)} -> {len(new_bytes)} bytes.[/green]"
                )
                self.call_after_refresh(self.do_jump_factory(tree, node))
            else:
                self.query_one("#breadcrumb", Label).update(
                    "[dim]Stream unchanged. Editing canceled.[/dim]"
                )
        except Exception as e:
            self.query_one("#breadcrumb", Label).update(
                f"[red]Error saving stream data:[/red] {e}"
            )

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
            self.query_one("#breadcrumb", Label).update(f"[red]Failed to save PDF:[/red] {e}")

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
            f"Search {direction_text}  —  Enter to jump · Esc or ctrl+g to cancel"
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
            self.query_one("#breadcrumb", Label).update(f"[red]Invalid page number:[/red] {value}")
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
            expand_to(target_node)

            tree = self.query_one("#tree-pane", PDFTree)

            self.call_after_refresh(self.do_jump_factory(tree, target_node))

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

        all_nodes = list(iter_nodes(tree.root))

        start_node = tree.cursor_node
        try:
            start_idx = all_nodes.index(start_node)
        except ValueError:
            start_idx = -1

        if self._search_direction == "forward":
            if start_idx == -1:
                search_sequence = all_nodes
            else:
                search_sequence = all_nodes[start_idx + 1 :] + all_nodes[: start_idx + 1]
        else:
            if start_idx == -1:
                search_sequence = all_nodes[::-1]
            else:
                search_sequence = all_nodes[:start_idx][::-1] + all_nodes[start_idx:][::-1]

        match = next((n for n in search_sequence if query in n.label.plain.lower()), None)

        if match:
            expand_to(match)
            self.call_after_refresh(self.do_jump_factory(tree, match))
            status = f"[green]Found:[/green] {query}"
        else:
            status = f"[red]Not found:[/red] {query}"

        self.query_one("#breadcrumb", Label).update(status)

    # -------------------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield PDFTree(f"[bold magenta]{self.pdf_path}[/bold magenta]", id="tree-pane")
            with Vertical(id="right-pane"):
                yield Label("Trailer", id="breadcrumb")
                yield RichLog(id="details-pane", highlight=True, wrap=True, auto_scroll=False)
        yield SearchInput(
            placeholder="Search nodes (Enter to jump, Esc or ctrl+g to cancel)...",
            id="search-bar",
        )
        yield PageInput(
            placeholder="Go to page (Enter to jump, Esc or ctrl+g to cancel)...",
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
            parts.append(get_node_name(curr))
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
                expand_to(target)
                self.call_after_refresh(self.do_jump_factory(tree, target))
                log.write(Text.from_markup("[bold yellow]--- Jumped to Object ---[/bold yellow]"))
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
                log.write(Text.from_markup(f"[bold red]Error reading stream:[/bold red] {e}"))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _startup_selection(self, tree: PDFTree) -> None:
        pages_node = get_node_by_path(tree, ["Trailer", "/Root", "/Pages"])
        if pages_node:
            expand_to(pages_node)
            pages_node.expand()
            self.call_after_refresh(lambda: tree.select_node(pages_node))
            tree.focus()


def main():
    if len(sys.argv) < 2 or "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print("Usage: python tree_tui.py <file.pdf>")
        sys.exit(1)

    app = PDFTreeApp(sys.argv[1])
    app.run()

    # Force the terminal prompt below the leftover TUI ghost
    print("\033[999;1H\n", end="")


if __name__ == "__main__":
    main()
