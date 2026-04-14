import pikepdf
from rich.text import Text
from textual.widgets.tree import TreeNode


def is_content_stream(stream: pikepdf.Stream, name: str, parent_name: str = "") -> bool:
    # Fast exit: image codecs mean raw pixel data
    image_filters = {"/DCTDecode", "/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode"}
    filters = stream.get("/Filter")
    if filters is not None:
        filter_list = (
            [str(filters)] if not isinstance(filters, pikepdf.Array) else [str(f) for f in filters]
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


# -------------------------------------------------------------------------
# Node Type Handlers
# -------------------------------------------------------------------------


def _handle_dictionary(pdf_obj, parent_node, name, obj_label, is_ind, stack, registry):
    label = Text()
    label.append(name, style="bold blue")
    if obj_label:
        label.append(f" {obj_label}", style="dim yellow")
    label.append(f" Dict[{len(pdf_obj)}]", style="dim")

    new_node = parent_node.add(label, data=pdf_obj)
    if is_ind:
        registry[pdf_obj.objgen] = new_node

    for key, val in reversed(sorted(pdf_obj.items(), key=sort_pdf_keys)):
        stack.append((val, new_node, str(key), False))


def _handle_array(pdf_obj, parent_node, name, obj_label, stack):
    label = Text()
    label.append(name, style="bold green")
    if obj_label:
        label.append(f" {obj_label}", style="dim yellow")
    label.append(f" Array[{len(pdf_obj)}]", style="dim")

    new_node = parent_node.add(label, data=pdf_obj)
    is_kids_array = name == "/Kids"

    for i, val in reversed(list(enumerate(pdf_obj))):
        stack.append((val, new_node, f"[{i}]", is_kids_array))


def _handle_stream(pdf_obj, parent_node, name, obj_label, is_ind, stack, registry):
    label = Text()
    label.append(name, style="bold red")
    if obj_label:
        label.append(f" {obj_label}", style="dim yellow")
    label.append(" Stream", style="dim")

    new_node = parent_node.add(label, data=pdf_obj)
    if is_ind:
        registry[pdf_obj.objgen] = new_node

    for key, val in reversed(sorted(pdf_obj.items(), key=sort_pdf_keys)):
        stack.append((val, new_node, str(key), False))


def _handle_primitive(pdf_obj, parent_node, name, obj_label, is_ind, registry):
    val_str = str(pdf_obj)
    if len(val_str) > 60:
        val_str = val_str[:57] + "..."

    label = Text()
    label.append(name, style="bold cyan")
    if is_ind:
        label.append(f" {obj_label}", style="dim yellow")
    label.append(f": {val_str}")

    new_node = parent_node.add_leaf(label, data=pdf_obj)
    if is_ind:
        registry[pdf_obj.objgen] = new_node


# -------------------------------------------------------------------------
# Processing Flow Helpers
# -------------------------------------------------------------------------


def _process_node(pdf_obj, parent_node, name, is_kid, stack, registry, deferred_nodes):
    """Processes a single PDF object, handling jumps, defers, and routing to type handlers."""
    is_ind = getattr(pdf_obj, "is_indirect", False)
    obj_label = f"(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})" if is_ind else ""

    if is_ind:
        # 1. Existing object? Create a standard jump reference.
        if pdf_obj.objgen in registry:
            label = Text.from_markup(
                f"[dim underline italic]{name}: ↪ Jump to Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}[/]"
            )
            parent_node.add_leaf(label, data=JumpReference(registry[pdf_obj.objgen]))
            return

        # 2. Page dictionary not inside /Kids? Defer it.
        obj_type = pdf_obj.get("/Type") if isinstance(pdf_obj, pikepdf.Dictionary) else None
        if str(obj_type) == "/Page" and not is_kid:
            label = Text.from_markup(
                f"[dim underline italic]{name}: ↪ [Deferred] Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}[/]"
            )
            new_node = parent_node.add(label, data=DeferredJumpReference(pdf_obj, name))
            deferred_nodes.append(new_node)
            return

    # Route to the specific type handler
    if isinstance(pdf_obj, pikepdf.Dictionary):
        _handle_dictionary(pdf_obj, parent_node, name, obj_label, is_ind, stack, registry)
    elif isinstance(pdf_obj, pikepdf.Array):
        _handle_array(pdf_obj, parent_node, name, obj_label, stack)
    elif isinstance(pdf_obj, pikepdf.Stream):
        _handle_stream(pdf_obj, parent_node, name, obj_label, is_ind, stack, registry)
    else:
        _handle_primitive(pdf_obj, parent_node, name, obj_label, is_ind, registry)


def _resolve_orphans(deferred_nodes, registry, stack) -> bool:
    """Processes deferred nodes. Returns True if unresolved orphans were found."""
    unresolved_orphans = False

    # Copy and clear so we can safely iterate
    current_deferred = deferred_nodes[:]
    deferred_nodes.clear()

    for node in current_deferred:
        data = node.data
        pdf_obj = data.pdf_obj

        if pdf_obj.objgen in registry:
            # Happy path: The page was successfully built by the /Kids array
            label = Text.from_markup(
                f"[dim underline italic]{data.original_name}: ↪ Jump to Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}[/]"
            )
            node.set_label(label)
            node.data = JumpReference(registry[pdf_obj.objgen])
            node.allow_expand = False
        else:
            # Orphan path: The page is broken and missing from /Kids
            unresolved_orphans = True
            registry[pdf_obj.objgen] = node
            node.data = pdf_obj

            # Revert the label to look like a standard dictionary
            label = Text()
            label.append(data.original_name, style="bold blue")
            label.append(f" (Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})", style="dim yellow")
            label.append(f" Dict[{len(pdf_obj)}]", style="dim")

            node.set_label(label)
            node.allow_expand = True

            # Push its children onto the stack to resume DFS
            for key, val in reversed(sorted(pdf_obj.items(), key=sort_pdf_keys)):
                stack.append((val, node, str(key), False))

    return unresolved_orphans


# -------------------------------------------------------------------------
# Main Entry Point
# -------------------------------------------------------------------------


def build_tree(pdf_root, tree_root: TreeNode, node_registry=None, name="Trailer"):
    if node_registry is None:
        node_registry = {}

    deferred_nodes = []
    stack = [(pdf_root, tree_root, name, False)]

    while True:
        # Phase 1: Build down the tree
        while stack:
            pdf_obj, parent_node, current_name, is_kid = stack.pop()
            _process_node(
                pdf_obj, parent_node, current_name, is_kid, stack, node_registry, deferred_nodes
            )

        # Phase 2: Post-processing and orphan recovery
        found_orphans = _resolve_orphans(deferred_nodes, node_registry, stack)

        # If no orphans were found, the stack remains empty and we are done.
        if not found_orphans:
            break
