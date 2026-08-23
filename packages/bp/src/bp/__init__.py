"""bp -- builder primitives.

Inert markup for AST-addressable Python nodes. Five constructs, zero dependencies,
no runtime behavior:

    from bp import node, group_node, editable, generated, Param

An application annotated with these executes identically to one without them.
That property is invariant I-2 in docs/architecture.md, and `aibuilder strip`
checks it mechanically.
"""

from bp.markers import GroupNode, editable, generated, group_node, node
from bp.param import Param

__all__ = ["node", "group_node", "editable", "generated", "Param", "GroupNode"]
__version__ = "0.1.0"
