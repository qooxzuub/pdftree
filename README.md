# **pdftree**

A Text User Interface for inspecting and modifying PDF object structures. Built with Python, Textual, and pikepdf.

<a href="https://raw.githubusercontent.com/qooxzuub/pdftree/main/.github/assets/screenshot.png"><img align="center" width="100%" src="https://raw.githubusercontent.com/qooxzuub/pdftree/main/.github/assets/screenshot.png"></a>


## **Features**

* **Tree Inspection:** Navigate the internal dictionary, array, and stream structures of PDF files using Vim-style keybindings.

* **Stream Decoding:**  Decompresses and displays the raw text of PDF content streams in a secondary pane: navigate to a stream and press `enter`.

* **Stream Editing:** Press `e` on a stream node to extract it to a temporary file, open it in your local `$EDITOR`, and inject the saved changes back into the PDF.

* **Stream Normalization:** Press `f` to format dense content streams, parsing the data to place one PDF operator per line.

* **Stream and Image Extraction:** Press `s` to save an uncompressed stream to disk, or `x` to extract an image stream.

* **Reference Navigation:** Follow object references (e.g., `/Parent`) via interactive links, or jump to specific pages using `g`.

* **Search:** Search forward (`/`) and backward (`?`) through tree node labels.

## **Installation**

pdftree requires **Python 3.10** or higher.

Install it globally using pipx (recommended for CLI tools):

```
pipx install pdftree
```

Or install it via standard pip:

```
pip install pdftree
```

## **Usage**

Launch the TUI by passing the path to any PDF file:

```
pdftree path/to/document.pdf
```

### **Keybindings**

You can press F1 or H at any time inside the app to bring up this cheat sheet.

| Key | Action |
| :---- | :---- |
| **F1** / **H** | Show/Hide the help menu |
| **/** | Search forward |
| **?** | Search backward |
| **n** / **p** | Repeat search forward / backward |
| **Esc** / **Ctrl+G** | Cancel search or close modals |
| **j** / **k** / **↓** / **↑** | Navigate tree vertically |
| **h** / **←** | Collapse node / Jump to parent |
| **l** / **→** | Expand node / Jump to first child |
| **g** | Go to page... |
| **s** | Save stream content to disk |
| **f** | Format/normalize stream content |
| **e** | Edit stream content in `$EDITOR` |
| **w** | Save the modified PDF to disk |
| **x** | Extract image to disk |
| **Enter** | Follow link / Open stream |
| **Ctrl+Z** | Suspend process |
| **Ctrl+L** | Force screen redraw |
| **q** / **Ctrl+C** | Quit application (prompts if unsaved changes) |

## **License**

MPL-2.0
