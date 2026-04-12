from rich.text import Text
from textual.widgets.tree import TreeNode
from textual.widgets import Tree as TextualTree


def expand_to(node: TreeNode) -> None:
    """Expand all ancestors so a node is visible in the tree."""
    curr = node.parent
    while curr is not None:
        curr.expand()
        curr = curr.parent

def get_node_name(node):
    label_str = node.label.plain if hasattr(node.label, "plain") else str(node.label)
    return label_str.split()[0]

def get_node_by_path(tree: TextualTree, path_steps: list[str]) -> TreeNode | None:
    current_node = tree.root
    for step in path_steps:
        found = False
        for child in current_node.children:
            if step in child.label.plain:
                current_node = child
                found = True
                break
        if not found:
            return None
    return current_node

def rebuild_stream_label(node: TreeNode, new_length: int | None = None) -> None:
    """Reconstruct a stream node's Text label with an updated byte count."""
    # node.label.plain looks like "/Contents (Obj 5:0) Stream"
    # We have all the info we need in node.data
    stream = node.data
    name = get_node_name(node)
    is_ind = getattr(stream, "is_indirect", False)

    label = Text()
    label.append(name, style="bold red")
    if is_ind:
        label.append(f" (Obj {stream.objgen[0]}:{stream.objgen[1]})", style="dim yellow")
    label.append(" Stream", style="dim")
    if new_length is not None:
        label.append(f" {int(new_length)} bytes", style="dim")
    node.set_label(label)


def iter_nodes(root: TreeNode):
    """Iterative pre-order traversal — avoids recursion-limit issues on deep trees."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        # Push children in reverse so left-most child is processed first
        for child in reversed(node.children):
            stack.append(child)
