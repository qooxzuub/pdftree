import pikepdf
from textual.widgets.tree import TreeNode


def is_content_stream(stream: pikepdf.Stream, name: str, parent_name: str = "") -> bool:
    # Fast exit: image codecs mean raw pixel data
    image_filters = {"/DCTDecode", "/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode"}
    filters = stream.get("/Filter")
    if filters is not None:
        filter_list = (
            [str(filters)]
            if not isinstance(filters, pikepdf.Array)
            else [str(f) for f in filters]
        )
        if any(f in image_filters for f in filter_list):
            return False

    obj_type = str(stream.get("/Type", ""))
    obj_subtype = str(stream.get("/Subtype", ""))

    if name == "/Contents" or parent_name == "/Contents":
        return True
    if obj_type == "/Pattern":  # PatternType 1 tiling patterns
        return True
    if obj_type == "/XObject" and obj_subtype == "/Form":
        return True
    # Appearance streams have no /Type but are content streams
    if name in ("/N", "/R", "/D") and obj_type == "":
        return True  # heuristic — could false-positive on other anonymous streams

    return False


def sort_pdf_keys(item):
    key, val = item
    str_key = str(key)
    if str_key == "/Type":
        priority = -1
    elif str_key in ("/Root", "/Pages", "/Kids"):
        priority = 0
    elif isinstance(val, (pikepdf.Dictionary, pikepdf.Array, pikepdf.Stream)):
        priority = 2
    else:
        priority = 1
    return (priority, str_key)


class JumpReference:
    def __init__(self, target_node: TreeNode):
        self.target_node = target_node


class DeferredJumpReference:
    """Stores the actual object so we can build it later if it turns out to be an orphan."""

    def __init__(self, pdf_obj, original_name):
        self.pdf_obj = pdf_obj
        self.original_name = original_name


class TreeAdapter:
    """Interface to be implemented by TUI and GUI."""

    def create_node(self, parent, pdf_obj, name, label_type):
        pass

    def create_jump(self, parent, target_node, name):
        pass

    def create_deferred(self, parent, pdf_obj, name):
        pass

    def resolve_deferred(self, deferred_node, target_node, name, is_orphan):
        pass


def walk_pdf(pdf_root, adapter, name="Trailer"):
    registry = {}  # objgen -> UI Node handle
    deferred = []  # List of (UI handle, pdf_obj, name)
    stack = [(pdf_root, None, name, False)]  # (obj, ui_parent, name, is_kid)

    while True:
        # --- PHASE 1: Build down the tree ---
        while stack:
            obj, parent_ui, n, is_kid = stack.pop()
            is_ind = getattr(obj, "is_indirect", False)

            # 1. Handle Jumps (Cycles)
            if is_ind and obj.objgen in registry:
                adapter.create_jump(parent_ui, registry[obj.objgen], n)
                continue

            # 2. Handle Deferred (Matching your _process_node logic)
            obj_type = obj.get("/Type") if isinstance(obj, pikepdf.Dictionary) else None
            if is_ind and str(obj_type) == "/Page" and not is_kid:
                # Instead of adding a node directly, we let the adapter create a placeholder
                ui_handle = adapter.create_deferred(parent_ui, obj, n)
                deferred.append((ui_handle, obj, n))
                continue

            # 3. Create Standard Node
            if isinstance(obj, pikepdf.Dictionary):
                node_type = "Dictionary"
            elif isinstance(obj, pikepdf.Array):
                node_type = "Array"
            elif isinstance(obj, pikepdf.Stream):
                node_type = "Stream"
            else:
                node_type = type(obj).__name__
            ui_handle = adapter.create_node(parent_ui, obj, n, node_type)
            if is_ind:
                registry[obj.objgen] = ui_handle

            # 4. Discovery (Push children to stack)
            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                # Uses your sort_pdf_keys helper
                for key, val in reversed(sorted(obj.items(), key=sort_pdf_keys)):
                    stack.append((val, ui_handle, str(key), False))
            elif isinstance(obj, pikepdf.Array):
                is_kids_array = n == "/Kids"
                for i, val in reversed(list(enumerate(obj))):
                    stack.append((val, ui_handle, f"[{i}]", is_kids_array))

        # --- PHASE 2: Orphan Recovery (Matching _resolve_orphans) ---
        found_new_orphans = False
        current_deferred = deferred[:]
        deferred.clear()

        for ui_handle, obj, n in current_deferred:
            if obj.objgen in registry:
                # Happy path: Page was found in /Kids, turn placeholder into a Jump
                adapter.resolve_deferred(
                    ui_handle, registry[obj.objgen], n, is_orphan=False
                )
            else:
                # Orphan path: Page is broken/missing, "promote" it and resume DFS
                found_new_orphans = True
                registry[obj.objgen] = ui_handle
                adapter.resolve_deferred(ui_handle, obj, n, is_orphan=True)

                # Push children to the stack so Phase 1 starts again
                for key, val in reversed(sorted(obj.items(), key=sort_pdf_keys)):
                    stack.append((val, ui_handle, str(key), False))

        if not found_new_orphans and not stack:
            break
