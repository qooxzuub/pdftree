import sys

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango

import pikepdf
import html

# Import our decoupled engine
from .pdf_utils import walk_pdf, TreeAdapter, JumpReference
from .actions import ActionHandler
from .events import EventHandler

# --- PASTE GtkAdapter CLASS HERE (from block above) ---
class GtkAdapter(TreeAdapter):
    def __init__(self, store):
        self.store = store
        self.registry = {}

    def create_node(self, parent_iter, pdf_obj, name, label_type):
        is_ind = getattr(pdf_obj, "is_indirect", False)
        
        # Markup labels
        obj_label = f" <span color='#c4a000'>(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})</span>" if is_ind else ""
        # Raw text labels
        raw_obj_label = f" (Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})" if is_ind else ""

        if label_type == "Dictionary":
            markup = f"<span color='#729fcf'><b>{name}</b></span>{obj_label} <span color='gray'>Dict[{len(pdf_obj)}]</span>"
            raw_text = f"{name}{raw_obj_label} Dict[{len(pdf_obj)}]"
        elif label_type == "Array":
            markup = f"<span color='#8ae234'><b>{name}</b></span>{obj_label} <span color='gray'>Array[{len(pdf_obj)}]</span>"
            raw_text = f"{name}{raw_obj_label} Array[{len(pdf_obj)}]"
        elif label_type == "Stream":
            markup = f"<span color='#ef2929'><b>{name}</b></span>{obj_label} <span color='gray'>Stream</span>"
            raw_text = f"{name}{raw_obj_label} Stream"
        else:
            raw_val = str(pdf_obj)[:60]
            val_str = html.escape(raw_val)
            markup = f"<span color='#34e2e2'><b>{name}</b></span>: {val_str}"
            raw_text = f"{name}: {raw_val}"

        new_iter = self.store.append(parent_iter, [markup, pdf_obj, raw_text, name])
        if is_ind: self.registry[pdf_obj.objgen] = new_iter
        return new_iter

    def create_jump(self, parent_iter, target_iter, name):
        markup = f"<span color='gray'><i>↪ {name} (Jump)</i></span>"
        raw_text = f"↪ {name} (Jump)"
        target_path = self.store.get_path(target_iter)
        self.store.append(parent_iter, [markup, JumpReference(target_path), raw_text, name])

    def create_deferred(self, parent_iter, pdf_obj, name):
        markup = f"<span color='gray'><i>{name} [Deferred]</i></span>"
        raw_text = f"{name} [Deferred]"
        return self.store.append(parent_iter, [markup, pdf_obj, raw_text, name])

    def resolve_deferred(self, ui_iter, target, name, is_orphan):
        if is_orphan:
            pdf_obj = target
            markup = f"<span color='#729fcf'><b>{name}</b></span> <span color='#c4a000'>(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})</span> <span color='gray'>Dict[{len(pdf_obj)}]</span>"
            raw_text = f"{name} (Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}) Dict[{len(pdf_obj)}]"
            
            self.store.set_value(ui_iter, 0, markup)
            self.store.set_value(ui_iter, 1, pdf_obj)
            self.store.set_value(ui_iter, 2, raw_text)
            self.store.set_value(ui_iter, 2, name)
        else:
            markup = f"<span color='gray'><i>↪ {name} (Jump)</i></span>"
            raw_text = f"↪ {name} (Jump)"
            target_path = self.store.get_path(target)

            self.store.set_value(ui_iter, 0, markup)
            self.store.set_value(ui_iter, 1, JumpReference(target_path))
            self.store.set_value(ui_iter, 2, raw_text)
            self.store.set_value(ui_iter, 3, name)


# ------------------------------------------------------


class PDFTreeGUI(Gtk.Window):
    def __init__(self, pdf_path):
        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-theme-name", "Adwaita-dark")
        super().__init__(title=f"pdftree GUI - {pdf_path}")
        self.set_default_size(1200, 700)
        self.actions = ActionHandler(self)
        self.events = EventHandler(self)
        
        try:
            self.pdf = pikepdf.Pdf.open(pdf_path)
        except Exception as e:
            print(f"Failed to open PDF: {e}")
            sys.exit(1)

        # --- MASTER LAYOUT ---
        self.main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(self.main_vbox)

        # 1. Menu Bar
        self.setup_menus()
        self.main_vbox.pack_start(self.menubar, False, False, 0)

        # 2. Paned Window (Left/Right)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_vbox.pack_start(self.paned, True, True, 0)

        # --- LEFT: TREE & SEARCH ---
        left_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.store = Gtk.TreeStore(str, object, str, str)
        self.tree_view = Gtk.TreeView(model=self.store)
        
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("PDF Structure", renderer, markup=0)
        self.tree_view.append_column(column)
        
        sw_tree = Gtk.ScrolledWindow()
        sw_tree.add(self.tree_view)
        left_vbox.pack_start(sw_tree, True, True, 0)

        self.search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry()
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.add(self.search_entry)
        left_vbox.pack_end(self.search_bar, False, False, 0)

        self.paned.pack1(left_vbox, True, False)
        self.paned.set_position(400) 

        # --- RIGHT: DETAILS & CONTENT ---
        right_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        
        self.breadcrumb_label = Gtk.Label(label="<b>Path:</b> /", use_markup=True)
        self.breadcrumb_label.set_halign(Gtk.Align.START)
        self.breadcrumb_label.set_margin_top(6)
        self.breadcrumb_label.set_margin_bottom(6)
        self.breadcrumb_label.set_margin_start(6)
        right_vbox.pack_start(self.breadcrumb_label, False, False, 0)

        self.right_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right_vbox.pack_start(self.right_paned, True, True, 0)

        self.metadata_view = Gtk.TextView()
        self.metadata_view.set_editable(False)
        self.metadata_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw_meta = Gtk.ScrolledWindow()
        sw_meta.add(self.metadata_view)
        self.right_paned.pack1(sw_meta, False, False)
        self.right_paned.set_position(100) 

        self.content_view = Gtk.TextView()
        self.content_view.set_editable(False)
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"textview { font: 12pt monospace; }")
        self.content_view.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        sw_content = Gtk.ScrolledWindow()
        sw_content.add(self.content_view)
        self.right_paned.pack2(sw_content, True, False)

        self.paned.pack2(right_vbox, True, True)

        # Search State
        self.search_matches = []
        self.current_match_index = -1

        # Connections
        self.tree_view.get_selection().connect("changed", self.events.on_selection_changed)
        self.tree_view.connect("key-press-event", self.events.on_tree_key_press)
        self.tree_view.connect("button-press-event", self.events.on_tree_right_click)
        self.tree_view.connect("row-activated", self.events.on_tree_row_activated)

        self.search_entry.connect("search-changed", self.events.on_search_changed)
        self.search_entry.connect("next-match", self.events.on_search_next)       
        self.search_entry.connect("previous-match", self.events.on_search_prev)   
        self.search_entry.connect("stop-search", self.events.on_search_cancel)    
        self.connect("destroy", Gtk.main_quit)

        self.populate_ui_tree()
        self.show_all()
        self.expand_to_pages()

    # ==========================================
    # MENU & ACTION SETUP
    # ==========================================
    def setup_menus(self):
        """Builds both the top MenuBar and the Context Menu."""
        self.menubar = Gtk.MenuBar()
        self.context_menu = Gtk.Menu()
        
        def append_menuitems(items, parent):
            for item in items:
                item.set_use_underline(True)
                parent.append(item)

        # File Menu (Top Bar only)
        file_menu = Gtk.Menu()
        file_item = Gtk.MenuItem(label="_File")
        file_item.set_submenu(file_menu)
        append_menuitems([file_item], self.menubar)

        item_save = Gtk.MenuItem(label="_Save PDF As... (w)")
        item_save.connect("activate", self.actions.action_save_pdf)
        item_quit = Gtk.MenuItem(label="E_xit (Ctrl+q)")
        item_quit.connect("activate", Gtk.main_quit)
        append_menuitems([item_save, item_quit], file_menu)

        # Action Menu (Shared between Top Bar and Context Menu)
        action_menu = Gtk.Menu()
        action_item = Gtk.MenuItem(label="_Actions")
        action_item.set_submenu(action_menu)
        append_menuitems([action_item], self.menubar)

        # Define actions tuple: (Label, Handler)
        actions = [
            ("_Edit Stream / Value (e)", self.actions.action_edit),
            ("E_xtract Stream / Image (s)", self.actions.action_extract),
            ("_Normalize Stream (f)", self.actions.action_normalize),
            ("_Delete Node (Del)", self.actions.action_delete),
            ("_Jump to Page (g)", self.actions.action_jump_page)
        ]

        # Populate both menus
        for label, handler in actions:
            # Top Menu
            top_mi = Gtk.MenuItem(label=label)
            top_mi.connect("activate", handler)
            append_menuitems([top_mi], action_menu)
            # Context Menu
            ctx_mi = Gtk.MenuItem(label=label)
            ctx_mi.connect("activate", handler)
            append_menuitems([ctx_mi], self.context_menu)

        # Required so the context menu items are visible when popped up
        self.context_menu.show_all()


    def expand_to_pages(self):
        """Recursively search the TreeStore for the /Pages dictionary and expand to it."""
        def search_for_pages(tree_iter):
            while tree_iter:
                pdf_obj = self.store[tree_iter][1]
                
                # Check if this node is a Dictionary and its /Type is /Pages
                if isinstance(pdf_obj, pikepdf.Dictionary):
                    if str(pdf_obj.get("/Type", "")) == "/Pages":
                        return self.store.get_path(tree_iter)
                
                # Recurse into children
                if self.store.iter_has_child(tree_iter):
                    child_iter = self.store.iter_children(tree_iter)
                    result = search_for_pages(child_iter)
                    if result: return result
                
                tree_iter = self.store.iter_next(tree_iter)
            return None

        # Start search from the root (Trailer)
        first_iter = self.store.get_iter_first()
        pages_path = search_for_pages(first_iter)
        
        if pages_path:
            self.tree_view.expand_to_path(pages_path)
            self.tree_view.set_cursor(pages_path, None, False)
            # Scroll so the /Pages node is exactly in the middle of the screen
            self.tree_view.scroll_to_cell(pages_path, None, True, 0.5, 0.0)

    def populate_ui_tree(self):
        adapter = GtkAdapter(self.store)
        # Let the universal engine do the work
        walk_pdf(self.pdf.trailer, adapter, name="Trailer")


    def _jump_to_current_match(self):
        path = self.search_matches[self.current_match_index]
        self.tree_view.expand_to_path(path)
        self.tree_view.set_cursor(path, None, False)
        self.tree_view.scroll_to_cell(path, None, True, 0.5, 0.0)
    

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.pdftree.gui <file.pdf>")
        sys.exit(1)
        
    app = PDFTreeGUI(sys.argv[1])
    Gtk.main()
