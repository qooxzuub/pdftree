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


def build_tree(pdf_root, tree_root: TreeNode, node_registry=None, name="Trailer"):
    if node_registry is None:
        node_registry = {}

    # Stack items: (pdf_obj, parent_tree_node, name)
    stack = [(pdf_root, tree_root, name)]

    while stack:
        pdf_obj, parent_node, current_name = stack.pop()

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
            obj_label_text = f"(Obj {pdf_obj.objgen[0]}:{pdf_obj.objgen[1]})"

        if isinstance(pdf_obj, pikepdf.Dictionary):
            label.append(current_name, style="bold blue")
            if obj_label_text:  # the "(Obj N:M)" part
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(f" Dict[{len(pdf_obj)}]", style="dim")
            new_node = parent_node.add(label, data=pdf_obj)

            if is_ind:
                node_registry[pdf_obj.objgen] = new_node
            # Push children in reverse so they're processed in original order
            for key, val in sorted(pdf_obj.items(), key=sort_pdf_keys, reverse=True):
                stack.append((val, new_node, str(key)))

        elif isinstance(pdf_obj, pikepdf.Array):
            label.append(current_name, style="bold green")
            if obj_label_text:
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(f" Array[{len(pdf_obj)}]", style="dim")

            new_node = parent_node.add(label, data=pdf_obj)
            for i, val in reversed(list(enumerate(pdf_obj))):
                stack.append((val, new_node, f"[{i}]"))

        elif isinstance(pdf_obj, pikepdf.Stream):
            label.append(current_name, style="bold red")
            if obj_label_text:
                label.append(f" {obj_label_text}", style="dim yellow")
            label.append(" Stream", style="dim")
            new_node = parent_node.add(label, data=pdf_obj)

            if is_ind:
                node_registry[pdf_obj.objgen] = new_node
            for key, val in sorted(pdf_obj.items(), key=sort_pdf_keys, reverse=True):
                stack.append((val, new_node, str(key)))

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


class JumpReference:
    """A safe wrapper to tell the UI that this node is a hyperlink to another node."""

    def __init__(self, target_node: TreeNode):
        self.target_node = target_node


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
