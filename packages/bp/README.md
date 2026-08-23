# bp — builder primitives

Inert markup for AST-addressable Python nodes. Four constructs, zero dependencies, no runtime
behavior.

```python
from bp import node, group_node, editable, Param
```

- `@node(id=..., kind=..., title=...)` — marks a single-carrier node; returns the carrier unchanged.
- `@editable(signature_locked=True)` — marks a function body as user-editable; returns it unchanged.
- `group_node(id=..., kind=..., title=..., members=[...])` — declares a node spanning several
  carriers, listed **by object reference**; returns a plain data record.
- `Param(...)` — knob metadata carried inside `typing.Annotated`.

This package is installed into the applications the builder generates, which is why it lives on its
own and depends on nothing. An application annotated with it runs identically to one without it —
invariant I-2 in [../../docs/architecture.md](../../docs/architecture.md).

The tests in [tests/test_inert.py](tests/test_inert.py) hold that line: they assert **object
identity** before and after decoration, not merely equivalent behavior.
