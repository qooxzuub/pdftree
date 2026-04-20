import gi


import pikepdf

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

class ActionHandler:
    def __init__(self, app):
        self.app = app

    def get_selected_pdf_obj(self):
        """Helper to get the currently selected object in the tree."""
        model, treeiter = self.app.tree_view.get_selection().get_selected()
        if treeiter:
            return model[treeiter][1]
        return None

    def action_save_pdf(self, widget):
        """Pops up a native Save dialog and writes the modified PDF to disk."""
        dialog = Gtk.FileChooserDialog(
            title="Save PDF As...",
            parent=self.app,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.ACCEPT,
        )
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name("modified.pdf")

        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            try:
                self.app.pdf.save(dialog.get_filename())
                print(f"Saved successfully to {dialog.get_filename()}")
            except Exception as e:
                print(f"Failed to save PDF: {e}")

        dialog.destroy()

    def action_delete(self, widget):
        """Deletes the selected node from both the UI and the actual Pikepdf structure."""
        model, treeiter = self.app.tree_view.get_selection().get_selected()
        if not treeiter:
            return

        parent_iter = model.iter_parent(treeiter)
        if not parent_iter:
            return  # Can't delete the root trailer!

        parent_obj = model[parent_iter][1]
        node_name = model[treeiter][3]  # The raw name (e.g. "/Font" or "[0]")

        try:
            # 1. Dictionary Deletion
            if isinstance(parent_obj, pikepdf.Dictionary):
                old_len = len(parent_obj)
                del parent_obj[node_name]
                new_len = len(parent_obj)

                # Update Parent UI Label
                p_markup = model[parent_iter][0].replace(
                    f"Dict[{old_len}]", f"Dict[{new_len}]"
                )
                p_raw = model[parent_iter][2].replace(
                    f"Dict[{old_len}]", f"Dict[{new_len}]"
                )
                model.set_value(parent_iter, 0, p_markup)
                model.set_value(parent_iter, 2, p_raw)

                model.remove(treeiter)

            # 2. Array Deletion (Requires UI Renumbering)
            elif isinstance(parent_obj, pikepdf.Array):
                old_len = len(parent_obj)
                idx = int(node_name.strip("[]"))
                del parent_obj[idx]
                new_len = len(parent_obj)

                # Update Parent UI Label
                p_markup = model[parent_iter][0].replace(
                    f"Array[{old_len}]", f"Array[{new_len}]"
                )
                p_raw = model[parent_iter][2].replace(
                    f"Array[{old_len}]", f"Array[{new_len}]"
                )
                model.set_value(parent_iter, 0, p_markup)
                model.set_value(parent_iter, 2, p_raw)

                # model.remove returns True and modifies treeiter to point to the next row
                valid = model.remove(treeiter)
                current_idx = idx

                while valid:
                    new_name = f"[{current_idx}]"
                    old_name = f"[{current_idx + 1}]"

                    # Safely replace the old index string in the markup and raw text
                    markup = model[treeiter][0].replace(
                        f"<b>{old_name}</b>", f"<b>{new_name}</b>", 1
                    )
                    raw_text = model[treeiter][2].replace(
                        f"{old_name}", f"{new_name}", 1
                    )

                    # Update columns 0 (markup), 2 (raw), and 3 (name)
                    model.set_value(treeiter, 0, markup)
                    model.set_value(treeiter, 2, raw_text)
                    model.set_value(treeiter, 3, new_name)

                    current_idx += 1

                    # Advance to the next sibling
                    treeiter = model.iter_next(treeiter)
                    valid = treeiter is not None

        except Exception as e:
            dialog = Gtk.MessageDialog(
                transient_for=self.app,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Deletion Failed",
            )
            dialog.format_secondary_text(str(e))
            dialog.run()
            dialog.destroy()

        self.app.tree_view.get_selection().emit("changed")


    def action_extract(self, widget):
        """Extracts the selected Stream or Image to a file."""
        obj = self.get_selected_pdf_obj()
        if not isinstance(obj, pikepdf.Stream):
            print("Selected object is not a stream.")
            return

        dialog = Gtk.FileChooserDialog(
            title="Extract Stream To...",
            parent=self.app,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.ACCEPT,
        )
        dialog.set_do_overwrite_confirmation(True)

        # Try to guess extension
        ext = ".bin"
        if str(obj.get("/Subtype", "")) == "/Image":
            filter_name = str(obj.get("/Filter", ""))
            if "DCTDecode" in filter_name:
                ext = ".jpg"
            elif "FlateDecode" in filter_name:
                ext = ".png"  # (Requires extra handling for raw PNG bytes, but close enough for now)
        dialog.set_current_name(f"extracted_stream{ext}")

        if dialog.run() == Gtk.ResponseType.ACCEPT:
            try:
                with open(dialog.get_filename(), "wb") as f:
                    f.write(obj.read_bytes())
                print("Stream extracted!")
            except Exception as e:
                print(f"Failed to extract stream: {e}")

        dialog.destroy()

    # ==========================================
    # ACTION HANDLERS (To be implemented)
    # ==========================================

    def action_edit(self, widget):
        obj = self.get_selected_pdf_obj()
        print(f"TODO: Edit object of type {type(obj).__name__}")

    def action_normalize(self, widget):
        print("TODO: Normalize stream")

    def action_jump_page(self, widget):
        """Prompts for a page number and jumps the tree to that PDF Dictionary."""
        total_pages = len(self.app.pdf.pages)
        if total_pages == 0:
            return

        # 1. Create the dialog
        dialog = Gtk.MessageDialog(
            transient_for=self.app,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Jump to Page",
        )
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.format_secondary_text(f"Enter page number (1 - {total_pages}):")

        entry = Gtk.Entry()
        entry.set_activates_default(True)
        dialog.get_message_area().pack_end(entry, False, False, 0)
        dialog.show_all()

        response = dialog.run()
        page_text = entry.get_text()
        dialog.destroy()

        # Helper function for GUI error messages
        def show_error(message):
            err_dialog = Gtk.MessageDialog(
                transient_for=self.app,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Invalid Input",
            )
            err_dialog.format_secondary_text(message)
            err_dialog.run()
            err_dialog.destroy()

        # 2. Process the input
        if response == Gtk.ResponseType.OK:
            try:
                page_num = int(page_text)  # This will raise ValueError on "asdkfjh"

                if 1 <= page_num <= total_pages:
                    target_page = self.app.pdf.pages[page_num - 1]
                    objgen = target_page.objgen
                    target_iter = self.app.adapter.registry.get(objgen)

                    if target_iter:
                        path = self.app.store.get_path(target_iter)
                        self.app.tree_view.expand_to_path(path)
                        self.app.tree_view.set_cursor(path, None, False)
                        self.app.tree_view.scroll_to_cell(path, None, True, 0.5, 0.0)
                        self.app.tree_view.grab_focus()
                    else:
                        show_error("Page node not found in the UI tree registry.")
                else:
                    show_error(
                        f"Invalid page number.\nMust be between 1 and {total_pages}."
                    )

            except ValueError:
                # Catches non-numbers and weird characters
                show_error(
                    f"Please enter a valid whole number between 1 and {total_pages}."
                )

    def expand_to_pages(self):
        """Recursively search the TreeStore for the /Pages dictionary and expand to it."""

        def search_for_pages(tree_iter):
            while tree_iter:
                pdf_obj = self.app.store[tree_iter][1]

                # Check if this node is a Dictionary and its /Type is /Pages
                if isinstance(pdf_obj, pikepdf.Dictionary):
                    if str(pdf_obj.get("/Type", "")) == "/Pages":
                        return self.app.store.get_path(tree_iter)

                # Recurse into children
                if self.app.store.iter_has_child(tree_iter):
                    child_iter = self.app.store.iter_children(tree_iter)
                    result = search_for_pages(child_iter)
                    if result:
                        return result

                tree_iter = self.app.store.iter_next(tree_iter)
            return None

        # Start search from the root (Trailer)
        first_iter = self.app.store.get_iter_first()
        pages_path = search_for_pages(first_iter)

        if pages_path:
            self.app.tree_view.expand_to_path(pages_path)
            self.app.tree_view.set_cursor(pages_path, None, False)
            # Scroll so the /Pages node is exactly in the middle of the screen
            self.app.tree_view.scroll_to_cell(pages_path, None, True, 0.5, 0.0)
