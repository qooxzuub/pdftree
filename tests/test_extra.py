"""
Extra tests covering:
  - obj_to_node registry population (regression for the adapter wiring bug)
  - _handle_page_jump edge cases
  - PageInput / SearchInput widget behaviour
  - UnsavedChangesScreen button handlers
"""

import pathlib
import pytest
import pikepdf

from textual.widgets import Label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_breadcrumb(app) -> str:
    return str(app.query_one("#breadcrumb", Label).render())


# ---------------------------------------------------------------------------
# Registry population — regression test for the adapter wiring bug
# ---------------------------------------------------------------------------


class TestRegistryPopulation:
    @pytest.mark.asyncio
    async def test_obj_to_node_non_empty_after_mount(self, simple_pdf):
        """obj_to_node must be populated; empty dict means the fix regressed."""
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test():
            assert len(app.obj_to_node) > 0, (
                "obj_to_node is empty — TextualTreeAdapter not writing to registry"
            )

    @pytest.mark.asyncio
    async def test_every_page_in_registry(self, multipage_pdf):
        """Every page object must have an entry so page jumps can resolve."""
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(multipage_pdf))
        async with app.run_test():
            for i, page in enumerate(app.pdf.pages):
                assert page.objgen in app.obj_to_node, (
                    f"Page {i + 1} (objgen={page.objgen}) missing from obj_to_node"
                )


# ---------------------------------------------------------------------------
# Page jump — happy path already covered by test_app.py; these cover the edges
# ---------------------------------------------------------------------------


class TestHandlePageJump:
    @pytest.mark.asyncio
    async def test_jump_page_zero_shows_error(self, simple_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            await pilot.press("0", "enter")
            assert "out of bounds" in get_breadcrumb(app).lower()

    @pytest.mark.asyncio
    async def test_jump_page_too_large_shows_error(self, simple_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            # Page 999 doesn't exist in a 1-page PDF
            for ch in "999":
                await pilot.press(ch)
            await pilot.press("enter")
            assert "out of bounds" in get_breadcrumb(app).lower()

    @pytest.mark.asyncio
    async def test_jump_non_integer_shows_error(self, simple_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            for ch in "abc":
                await pilot.press(ch)
            await pilot.press("enter")
            breadcrumb = get_breadcrumb(app).lower()
            assert "invalid" in breadcrumb

    @pytest.mark.asyncio
    async def test_jump_empty_input_does_nothing(self, simple_pdf):
        """Pressing Enter on an empty page input should not crash or show an error."""
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            original_breadcrumb = get_breadcrumb(app)
            await pilot.press("enter")
            # Breadcrumb should be unchanged (no error injected)
            assert get_breadcrumb(app) == original_breadcrumb

    @pytest.mark.asyncio
    async def test_successful_jump_updates_breadcrumb(self, simple_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            await pilot.press("1", "enter")
            assert "Jumped to Page 1" in get_breadcrumb(app)

    @pytest.mark.asyncio
    async def test_successful_jump_multi_page(self, multipage_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(multipage_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            await pilot.press("3", "enter")
            assert "Jumped to Page 3" in get_breadcrumb(app)


# ---------------------------------------------------------------------------
# PageInput / SearchInput widgets
# ---------------------------------------------------------------------------


class TestPageInputWidget:
    @pytest.mark.asyncio
    async def test_hidden_by_default(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import PageInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test():
            page_input = app.query_one("#page-input", PageInput)
            assert page_input.display is False

    @pytest.mark.asyncio
    async def test_g_key_shows_input(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import PageInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            page_input = app.query_one("#page-input", PageInput)
            assert page_input.display is True

    @pytest.mark.asyncio
    async def test_escape_hides_input(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import PageInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            await pilot.press("escape")
            page_input = app.query_one("#page-input", PageInput)
            assert page_input.display is False

    @pytest.mark.asyncio
    async def test_enter_hides_input(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import PageInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("g")
            await pilot.press("1", "enter")
            page_input = app.query_one("#page-input", PageInput)
            assert page_input.display is False


class TestSearchInputWidget:
    @pytest.mark.asyncio
    async def test_hidden_by_default(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import SearchInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test():
            search_bar = app.query_one("#search-bar", SearchInput)
            assert search_bar.display is False

    @pytest.mark.asyncio
    async def test_slash_shows_search(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import SearchInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("/")
            search_bar = app.query_one("#search-bar", SearchInput)
            assert search_bar.display is True

    @pytest.mark.asyncio
    async def test_escape_hides_search(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import SearchInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.press("escape")
            search_bar = app.query_one("#search-bar", SearchInput)
            assert search_bar.display is False

    @pytest.mark.asyncio
    async def test_enter_hides_search(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import SearchInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.press("T", "r", "a", "i", "l", "e", "r", "enter")
            search_bar = app.query_one("#search-bar", SearchInput)
            assert search_bar.display is False

    @pytest.mark.asyncio
    async def test_question_mark_shows_search(self, simple_pdf):
        from pdftree.app import PDFTreeApp
        from pdftree.widgets import SearchInput

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            await pilot.press("?")
            search_bar = app.query_one("#search-bar", SearchInput)
            assert search_bar.display is True


# ---------------------------------------------------------------------------
# UnsavedChangesScreen
# ---------------------------------------------------------------------------


class TestUnsavedChangesScreen:
    @pytest.mark.asyncio
    async def test_quit_confirmed_exits_app(self, simple_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            app.is_dirty = True
            await pilot.press("q")
            # The UnsavedChangesScreen should now be active
            assert len(app.screen_stack) > 1

            # Send key to confirm
            await pilot.press("y")
            # App should have exited — run_test context will have finished cleanly

    @pytest.mark.asyncio
    async def test_quit_cancelled_keeps_app_running(self, simple_pdf):
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            app.is_dirty = True
            await pilot.press("q")
            assert len(app.screen_stack) > 1

            # Send key to cancel (no)
            await pilot.press("n")
            # Screen stack should be back to just the main screen
            assert len(app.screen_stack) == 1

    @pytest.mark.asyncio
    async def test_clean_quit_skips_dialog(self, simple_pdf):
        """When is_dirty is False, pressing q should exit without showing the dialog."""
        from pdftree.app import PDFTreeApp

        app = PDFTreeApp(str(simple_pdf))
        async with app.run_test() as pilot:
            assert app.is_dirty is False
            stack_depth_before = len(app.screen_stack)
            await pilot.press("q")
            # No extra screen should have been pushed
            assert len(app.screen_stack) == stack_depth_before
