import pikepdf
from rich.text import Text
from textual.widgets.tree import TreeNode


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


def build_tree(pdf_root, tree_root: TreeNode, node_registry=None, name="Trailer"):
    if node_registry is None:
        node_registry = {}

    deferred_nodes = []
    stack = [(pdf_root, tree_root, name, False)]

    # Outer loop allows us to resume DFS if we find orphans
    while True:
        while stack:
            pdf_obj, parent_node, current_name, is_kid = stack.pop()

            obj_label_text = ""
            is_ind = getattr(pdf_obj, "is_indirect", False)
            label = Text()

            if is_ind:
                if pdf_obj.objgen in node_registry:
                    label.append(
                        f"{current_name}: ↪ Jump to Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}",
                        style="dim underline italic",
                    )
                    parent_node.add_leaf(label, data=JumpReference(node_registry[pdf_obj.objgen]))
                    continue

                obj_type = (
                    pdf_obj.get("/Type") if isinstance(pdf_obj, pikepdf.Dictionary) else None
                )
                is_page_dict = str(obj_type) == "/Page"

                if is_page_dict and not is_kid:
                    label.append(
                        f"{current_name}: ↪ [Deferred] Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}",
                        style="dim underline italic",
                    )
                    # Use .add() instead of .add_leaf() in case we have to give it children later
                    new_node = parent_node.add(
                        label, data=DeferredJumpReference(pdf_obj, current_name)
                    )
                    deferred_nodes.append(new_node)
                    continue

                obj_label_text = f"(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})"

            if isinstance(pdf_obj, pikepdf.Dictionary):
                label.append(current_name, style="bold blue")
                if obj_label_text:
                    label.append(f" {obj_label_text}", style="dim yellow")
                label.append(f" Dict[{len(pdf_obj)}]", style="dim")
                new_node = parent_node.add(label, data=pdf_obj)

                if is_ind:
                    node_registry[pdf_obj.objgen] = new_node

                for key, val in reversed(sorted(pdf_obj.items(), key=sort_pdf_keys)):
                    # Dictionaries don't pass the is_kid flag
                    stack.append((val, new_node, str(key), False))

            elif isinstance(pdf_obj, pikepdf.Array):
                label.append(current_name, style="bold green")
                if obj_label_text:
                    label.append(f" {obj_label_text}", style="dim yellow")
                label.append(f" Array[{len(pdf_obj)}]", style="dim")

                new_node = parent_node.add(label, data=pdf_obj)

                # If this array is named /Kids, all elements inside it are kids
                is_kids_array = current_name == "/Kids"

                for i, val in reversed(list(enumerate(pdf_obj))):
                    stack.append((val, new_node, f"[{i}]", is_kids_array))

            elif isinstance(pdf_obj, pikepdf.Stream):
                label.append(current_name, style="bold red")
                if obj_label_text:
                    label.append(f" {obj_label_text}", style="dim yellow")
                label.append(" Stream", style="dim")
                new_node = parent_node.add(label, data=pdf_obj)

                if is_ind:
                    node_registry[pdf_obj.objgen] = new_node

                for key, val in reversed(sorted(pdf_obj.items(), key=sort_pdf_keys)):
                    stack.append((val, new_node, str(key), False))

            else:
                val_str = str(pdf_obj)
                if len(val_str) > 60:
                    val_str = val_str[:57] + "..."
                label.append(current_name, style="bold cyan")
                if is_ind:
                    label.append(f" {obj_label_text}", style="dim yellow")
                label.append(f": {val_str}")
                new_node = parent_node.add_leaf(label, data=pdf_obj)
                if is_ind:
                    node_registry[pdf_obj.objgen] = new_node

        # --- POST-PROCESSING & ORPHAN RECOVERY ---
        unresolved_orphans = False

        # Copy and clear so we can safely iterate and potentially re-defer items if needed
        current_deferred = deferred_nodes[:]
        deferred_nodes.clear()

        for node in current_deferred:
            deferred_data = node.data
            pdf_obj = deferred_data.pdf_obj

            if pdf_obj.objgen in node_registry:
                # 1. Happy path: The page was successfully built by the /Kids array!
                label = Text()
                label.append(
                    f"{deferred_data.original_name}: ↪ Jump to Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]}",
                    style="dim underline italic",
                )
                node.set_label(label)
                node.data = JumpReference(node_registry[pdf_obj.objgen])
                node.allow_expand = False  # Remove the expansion arrow
            else:
                # 2. Orphan path: The page is broken and missing from /Kids!
                unresolved_orphans = True
                node_registry[pdf_obj.objgen] = node
                node.data = pdf_obj

                # Revert the label to look like a standard dictionary
                obj_label_text = f"(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})"
                label = Text()
                label.append(deferred_data.original_name, style="bold blue")
                label.append(f" {obj_label_text}", style="dim yellow")
                label.append(f" Dict[{len(pdf_obj)}]", style="dim")

                node.set_label(label)
                node.allow_expand = True

                # Push its children onto the stack so they get expanded!
                for key, val in reversed(sorted(pdf_obj.items(), key=sort_pdf_keys)):
                    stack.append((val, node, str(key), False))

        # If no orphans were found, the stack is empty and we are completely done.
        # If orphans WERE found, the stack now contains their children, and the loop resumes!
        if not unresolved_orphans:
            break


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
