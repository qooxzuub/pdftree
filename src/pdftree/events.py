import gi

from .pdf_utils import JumpReference

import pikepdf

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk  # noqa: E402

class EventHandler:
    def __init__(self, app):
        self.app = app

    def on_tree_right_click(self, widget, event):
        """Intercepts right-clicks on the tree to show the context menu."""
        if event.button == 3:  # 3 is Right-click
            path_info = self.app.tree_view.get_path_at_pos(int(event.x), int(event.y))
            if path_info:
                path, col, cell_x, cell_y = path_info
                # Force selection of the row that was right-clicked
                self.app.tree_view.set_cursor(path, col, False)
                # Show popup
                self.app.context_menu.popup_at_pointer(event)
                return True
        return False

    def on_tree_row_activated(self, tree_view, path, column):
        """Triggered on Double-Click or pressing Enter on a row."""
        model = tree_view.get_model()
        pdf_obj = model[path][1]

        if isinstance(pdf_obj, JumpReference) and pdf_obj.target_node is not None:
            # The target is the saved TreePath
            target_path = pdf_obj.target_node

            # Jump to it!
            self.app.tree_view.expand_to_path(target_path)
            self.app.tree_view.set_cursor(target_path, None, False)
            self.app.tree_view.scroll_to_cell(target_path, None, True, 0.5, 0.0)

            # Optional UX touch: momentarily flash the row or keep focus
            self.app.tree_view.grab_focus()

    def on_tree_key_press(self, widget, event):
        keyname = Gdk.keyval_name(event.keyval)
        # 1. Search shortcut (Ctrl+F)
        if (event.state & Gdk.ModifierType.CONTROL_MASK) and event.keyval in (
            Gdk.KEY_f,
            Gdk.KEY_F,
        ) or event.keyval == Gdk.KEY_slash:
            self.app.search_bar.set_search_mode(True)
            self.app.search_entry.grab_focus()
            return True

        # 2. Map single-key shortcuts directly to our action functions
        if keyname == "q":
            Gtk.main_quit()
        elif keyname == "w":
            self.app.actions.action_save_pdf(None)
        elif keyname == "s":
            self.app.actions.action_extract(None)
        elif keyname == "e":
            self.app.actions.action_edit(None)
        elif keyname == "f":
            self.app.actions.action_normalize(None)
        elif keyname == "g":
            self.app.actions.action_jump_page(None)
        elif keyname == "Delete":
            self.app.actions.action_delete(None)

        # 3. Arrow Key navigation
        if event.keyval == Gdk.KEY_Right or keyname == "l":
            path, col = self.app.tree_view.get_cursor()
            if path:
                self.app.tree_view.expand_row(path, False)
                return True

        elif event.keyval == Gdk.KEY_Left or keyname == "h":
            path, col = self.app.tree_view.get_cursor()
            if path:
                if self.app.tree_view.row_expanded(path):
                    self.app.tree_view.collapse_row(path)
                elif len(path) > 1:
                    self.app.tree_view.set_cursor(path[:-1], None, False)
                return True
            
        elif keyname == "j":
            self.app.tree_view.emit("move-cursor", Gtk.MovementStep.DISPLAY_LINES, 1)
            return True
            
        elif keyname == "k":
            self.app.tree_view.emit("move-cursor", Gtk.MovementStep.DISPLAY_LINES, -1)
            return True


        return False

    def on_search_changed(self, entry):
        text = entry.get_text().lower()
        self.app.search_matches = []
        if not text:
            return

        def do_search(tree_iter):
            while tree_iter:
                raw_text = self.app.store[tree_iter][2]
                if raw_text and text in raw_text.lower():
                    self.app.search_matches.append(self.app.store.get_path(tree_iter))
                if self.app.store.iter_has_child(tree_iter):
                    do_search(self.app.store.iter_children(tree_iter))
                tree_iter = self.app.store.iter_next(tree_iter)

        do_search(self.app.store.get_iter_first())

        if self.app.search_matches:
            self.app.current_match_index = 0
            self.app._jump_to_current_match()

    def on_search_next(self, entry):
        if self.app.search_matches:
            self.app.current_match_index = (self.app.current_match_index + 1) % len(
                self.app.search_matches
            )
            self.app._jump_to_current_match()

    def on_search_prev(self, entry):
        if self.app.search_matches:
            self.app.current_match_index = (self.app.current_match_index - 1) % len(
                self.app.search_matches
            )
            self.app._jump_to_current_match()

    def on_search_cancel(self, entry):
        self.app.search_bar.set_search_mode(False)
        self.app.tree_view.grab_focus()
        # Note: We no longer revert the cursor! You stay where the search left you.

    def on_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return

        # 1. Update Breadcrumbs
        path_names = []
        curr_iter = treeiter
        while curr_iter:
            path_names.insert(0, model[curr_iter][3])  # Get 'name' from col 3
            curr_iter = model.iter_parent(curr_iter)
        self.app.breadcrumb_label.set_markup(
            '<b>Path:</b><span color="gray">' + " &gt; ".join(path_names) + "</span>"
        )

        # 2. Update Details vs Content Split
        pdf_obj = model[treeiter][1]
        meta_buf = self.app.metadata_view.get_buffer()
        content_buf = self.app.content_view.get_buffer()

        meta_buf.set_text(f"Type: {type(pdf_obj).__name__}\nRepr: {str(pdf_obj)[:200]}")
        content_buf.set_text("")  # Clear content by default

        if isinstance(pdf_obj, pikepdf.Stream):
            try:
                # Add full dictionary to metadata, uncompressed bytes to content
                meta_buf.set_text(f"Stream Dictionary:\n{str(pdf_obj)}")
                content = pdf_obj.read_bytes().decode("utf-8", errors="replace")
                content_buf.set_text(content)
            except Exception as e:
                content_buf.set_text(f"Error reading stream: {e}")
        elif isinstance(pdf_obj, JumpReference):
            meta_buf.set_text(
                "Jump Reference\nFollows an indirect object reference to another part of the tree.\n"
                + "Double-click or press Enter to follow link."
            )
