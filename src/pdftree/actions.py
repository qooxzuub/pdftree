import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import pikepdf

class ActionHandler:
    def __init__(self, app):
        self.app = app
        
    def get_selected_pdf_obj(self):
        """Helper to get the currently selected object in the tree."""
        model, treeiter = self.app.tree_view.get_selection().get_selected()
        if treeiter: return model[treeiter][1]
        return None

    def action_save_pdf(self, widget):
        """Pops up a native Save dialog and writes the modified PDF to disk."""
        dialog = Gtk.FileChooserDialog(
            title="Save PDF As...", parent=self.app, action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.ACCEPT)
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
        """Deletes the selected node from both the UI TreeStore and the actual Pikepdf structure."""
        model, treeiter = self.app.tree_view.get_selection().get_selected()
        if not treeiter: return
        
        parent_iter = model.iter_parent(treeiter)
        if not parent_iter: return # Can't delete the root trailer!
        
        parent_obj = model[parent_iter][1]
        node_name = model[treeiter][3] # The raw name (e.g. "/Font" or "[0]")
        
        try:
            # 1. Delete from the actual PDF structure
            if isinstance(parent_obj, pikepdf.Dictionary):
                del parent_obj[node_name]
            elif isinstance(parent_obj, pikepdf.Array):
                idx = int(node_name.strip("[]"))
                del parent_obj[idx]
                
            # 2. Delete from the UI Tree
            model.remove(treeiter)
        except Exception as e:
            print(f"Could not delete node: {e}")

    def action_extract(self, widget):
        """Extracts the selected Stream or Image to a file."""
        obj = self.get_selected_pdf_obj()
        if not isinstance(obj, pikepdf.Stream):
            print("Selected object is not a stream.")
            return
            
        dialog = Gtk.FileChooserDialog(
            title="Extract Stream To...", parent=self.app, action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.ACCEPT)
        dialog.set_do_overwrite_confirmation(True)
        
        # Try to guess extension
        ext = ".bin"
        if str(obj.get("/Subtype", "")) == "/Image":
            filter_name = str(obj.get("/Filter", ""))
            if "DCTDecode" in filter_name: ext = ".jpg"
            elif "FlateDecode" in filter_name: ext = ".png" # (Requires extra handling for raw PNG bytes, but close enough for now)
        dialog.set_current_name(f"extracted_stream{ext}")
        
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            try:
                with open(dialog.get_filename(), 'wb') as f:
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
        print("TODO: Prompt for page number and expand tree to that node")
