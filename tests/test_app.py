from contextlib import contextmanager
from unittest.mock import PropertyMock, patch

import pikepdf
import pytest
from textual.widgets import Label, RichLog

from pdftree.app import PDFTreeApp
from pdftree.tree_utils import expand_to, iter_nodes
from pdftree.widgets import PageInput, PDFTree, SearchInput


async def test_app_startup(simple_pdf):
    """Test that the app boots, mounts widgets, and loads the PDF successfully."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        assert app.query_one("#tree-pane", PDFTree) is not None
        assert app.query_one("#details-pane", RichLog) is not None

        breadcrumb = app.query_one("#breadcrumb", Label)
        assert breadcrumb is not None


async def test_help_screen_toggle(simple_pdf):
    """Test that F1 opens and Escape closes the help modal."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        await pilot.press("f1")
        assert "HelpScreen" in type(app.screen).__name__

        await pilot.press("escape")
        assert "HelpScreen" not in type(app.screen).__name__


async def test_search_functionality(simple_pdf):
    """Test the search flow correctly finds a known tree node."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        await pilot.press("/")

        search_bar = app.query_one("#search-bar", SearchInput)
        assert search_bar.display is True

        await pilot.press(*list("contents"), "enter")

        assert search_bar.display is False
        breadcrumb = app.query_one("#breadcrumb", Label)
        assert "Found:" in str(breadcrumb.render())


async def test_page_jump_functionality(simple_pdf):
    """Test the 'g' key opens the page jumper and successfully navigates."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        await pilot.press("g")

        page_input = app.query_one("#page-input", PageInput)
        assert page_input.display is True

        await pilot.press("1", "enter")

        assert page_input.display is False
        breadcrumb = app.query_one("#breadcrumb", Label)
        assert "Jumped to Page 1" in str(breadcrumb.render())


# -------------------------------------------------------------------------
# Stream Manipulation & Unsaved Changes
# -------------------------------------------------------------------------


async def test_quit_with_unsaved_changes(simple_pdf):
    """Test that 'q' prompts for confirmation if is_dirty is True."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        # Artificially dirty the document
        app.is_dirty = True

        # Attempt to quit
        await pilot.press("q")
        await pilot.pause()

        # The modal screen should be active instead of exiting
        assert "UnsavedChangesScreen" in type(app.screen).__name__


async def test_format_stream(simple_pdf):
    """Test that 'f' formats a selected stream and marks the app as dirty."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        tree = app.query_one("#tree-pane", PDFTree)
        stream_node = next(n for n in iter_nodes(tree.root) if isinstance(n.data, pikepdf.Stream))

        with patch("textual.widgets.Tree.cursor_node", new_callable=PropertyMock) as mock_cursor:
            mock_cursor.return_value = stream_node

            # Press 'f' to format while the mock is active
            await pilot.press("f")
            await pilot.pause()

        # If is_dirty is True, the format succeeded and applied changes
        assert app.is_dirty is True


async def test_edit_stream(simple_pdf, monkeypatch):
    """Test that 'e' exports to a temp file, calls $EDITOR, and reads changes back."""
    app = PDFTreeApp(str(simple_pdf))

    # 1. Mock the suspend context manager so Textual doesn't crash in headless mode
    @contextmanager
    def mock_suspend(*args, **kwargs):
        yield

    monkeypatch.setattr("pdftree.app.PDFTreeApp.suspend", mock_suspend)

    # 2. Mock subprocess.run to intercept the temp file creation
    def mock_subprocess_run(cmd_list, **kwargs):
        temp_file_path = cmd_list[-1]
        with open(temp_file_path, "wb") as f:
            f.write(b"BT /F1 12 Tf 100 700 Td (MOCKED EDIT) Tj ET")
        return type("CompletedProcess", (), {"returncode": 0})()

    monkeypatch.setattr("pdftree.app.subprocess.run", mock_subprocess_run)

    async with app.run_test() as pilot:
        tree = app.query_one("#tree-pane", PDFTree)
        stream_node = next(n for n in iter_nodes(tree.root) if isinstance(n.data, pikepdf.Stream))

        with patch("textual.widgets.Tree.cursor_node", new_callable=PropertyMock) as mock_cursor:
            mock_cursor.return_value = stream_node

            await pilot.press("e")
            await pilot.pause()

        assert app.is_dirty is True


async def test_quit_with_unsaved_changes(simple_pdf):
    """Test that 'q' prompts for confirmation if is_dirty is True."""
    app = PDFTreeApp(str(simple_pdf))

    async with app.run_test() as pilot:
        # Artificially dirty the document
        app.is_dirty = True

        # Attempt to quit
        await pilot.press("q")
        await pilot.pause()

        # The modal screen should be active instead of exiting
        assert "UnsavedChangesScreen" in type(app.screen).__name__
