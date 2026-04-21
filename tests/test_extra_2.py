import pytest
from textual.app import App
from pdftree.widgets import PDFTree
from pdftree.screens import PromptScreen, HelpScreen

# --- WIDGETS.PY TESTS ---


class DummyTreeApp(App):
    """A minimal app to host our custom PDFTree."""

    def compose(self):
        yield PDFTree("Root")


# --- SCREENS.PY TESTS ---


class DummyScreenApp(App):
    """A minimal app to test pushing modals."""

    pass


@pytest.mark.asyncio
async def test_prompt_screen_submit_default():
    app = DummyScreenApp()
    result = None

    def save_result(res):
        nonlocal result
        result = res

    async with app.run_test() as pilot:
        # Pass a default placeholder
        screen = PromptScreen("Save As:", "output.pdf")
        app.push_screen(screen, save_result)
        await pilot.pause()

        # The input should be pre-filled with the default
        input_widget = screen.query_one("Input")
        assert input_widget.value == "output.pdf"

        # Pressing enter should submit the pre-filled value
        await pilot.press("enter")
        await pilot.pause()

        assert result == "output.pdf"


@pytest.mark.asyncio
async def test_prompt_screen_cancel():
    app = DummyScreenApp()
    result = "NOT_NONE"

    def save_result(res):
        nonlocal result
        result = res

    async with app.run_test() as pilot:
        screen = PromptScreen("Enter something:")
        app.push_screen(screen, save_result)
        await pilot.pause()

        # Pressing escape should dismiss with None
        await pilot.press("escape")
        await pilot.pause()

        assert result is None


@pytest.mark.asyncio
async def test_help_screen_dismiss():
    app = DummyScreenApp()
    async with app.run_test() as pilot:
        screen = HelpScreen()
        app.push_screen(screen)
        await pilot.pause()

        # We should have 2 screens: the background and the modal
        assert len(app.screen_stack) == 2

        # Pressing 'q' is bound to dismiss
        await pilot.press("q")
        await pilot.pause()

        # Back to just the main screen
        assert len(app.screen_stack) == 1
