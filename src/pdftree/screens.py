from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown

HELP_TEXT = """\
# Keybindings Explorer

Press q or H or F1 to dismiss this window.

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
        Binding("ctrl+g", "cancel", "Cancel"),
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
        Binding("ctrl+g", "cancel", "Cancel"),
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


class HelpScreen(ModalScreen):
    """A modal screen showing keybindings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Dismiss"),
        Binding("ctrl+g", "dismiss", "Dismiss"),
        Binding("f1", "dismiss", "Dismiss"),
        Binding("H", "dismiss", "Dismiss"),
        Binding("q", "dismiss", "Dismiss"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield Markdown(HELP_TEXT)

    def action_dismiss(self) -> None:
        self.dismiss()
