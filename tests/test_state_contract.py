"""P0-A1: WorkflowState schema contract test.

Structural guard (engineering-conventions spec):

1. Every ``WorkflowState`` key is either (a) returned as a top-level key by at
   least one active node / the HIL runner, or (b) listed in
   ``INPUT_ONLY_KEYS`` (keys set only at initial-state seeding time).
2. Every entry of ``INPUT_ONLY_KEYS`` is declared in the ``WorkflowState``
   TypedDict.

The audit mirrors the task's step 2.1: AST-walk
``graph/nodes/*.py`` + ``graph/runner.py``, collect the top-level string keys
of the dicts the node entry points (and their private helpers) return, and
treat ``var["k"] = v`` writes and annotated dict-literal assignments as part
of the returned update.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
NODES_DIR = ROOT / "graph" / "nodes"
RUNNER = ROOT / "graph" / "runner.py"

# Node entry points registered in graph/main.py, mapped to the module that
# implements them. The BUILD node is a factory returning
# openhands_build_wrapper (active) which delegates to private helpers and,
# as a fallback, to the legacy subgraph's build_output_mapping.
NODE_FILES = {
    "graph/nodes/discover.py": {"discover_node"},
    "graph/nodes/define.py": {"define_node"},
    "graph/nodes/plan.py": {"plan_node"},
    "graph/nodes/review.py": {"review_node"},
    "graph/nodes/openhands_build.py": {"openhands_build_wrapper"},
    "graph/nodes/seed_data.py": {"seed_data_node"},
    "graph/nodes/verify.py": {"verify_node"},
    "graph/nodes/ship.py": {"ship_node"},
    "graph/nodes/reflect.py": {"reflect_node"},
    "graph/runner.py": {
        "run_workflow",
        "build_resume_payload",
        "parse_formatted_input",
        "_interview_notes_from",
        "_parse_approval",
        "extract_interrupt_type",
        "resolve_interrupted_phase",
    },
    "graph/nodes/build_subgraph_legacy.py": {"build_output_mapping"},
}

# openhands_build_wrapper delegates to these private helpers whose return
# dicts are the actual partial state updates. Note: _parse_build_report is
# deliberately excluded — it returns a normalized build_report dict (a file
# artifact), which _merge_results then folds into the `artifacts` sub-dict,
# never into the top-level WorkflowState.
BUILD_CALLEES = {
    "graph/nodes/openhands_build.py": {
        "_run_local_subgraph",
        "_delegate_to_openhands",
        "_merge_results",
    }
}


class _ReturnKeys(ast.NodeVisitor):
    """Collect the top-level string keys a function returns as state updates.

    Captures:
    - dict-literal ``return {...}``
    - ``return var`` where ``var`` was assigned a dict literal (plain or
      annotated ``var: dict = {...}``)
    - ``var["k"] = v`` writes to a later-returned dict
    """

    def __init__(self):
        self.keys: set[str] = set()
        self.vars: dict[str, set[str]] = {}
        self.dict_writes: dict[str, set[str]] = {}

    @staticmethod
    def _dict_keys(node: ast.Dict) -> set[str]:
        out: set[str] = set()
        for k in node.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                out.add(k.value)
        return out

    def _record_var_dict(self, target, value):
        if isinstance(target, ast.Name) and isinstance(value, ast.Dict):
            self.vars.setdefault(target.id, set()).update(self._dict_keys(value))

    def visit_Assign(self, node):
        for target in node.targets:
            self._record_var_dict(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._record_var_dict(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if (
            isinstance(node.target, ast.Subscript)
            and isinstance(node.target.value, ast.Name)
            and isinstance(node.target.slice, ast.Constant)
            and isinstance(node.target.slice.value, str)
        ):
            self.dict_writes.setdefault(node.target.value.id, set()).add(
                node.target.slice.value
            )
        self.generic_visit(node)

    def visit_Return(self, node):
        self.generic_visit(node)
        value = node.value
        if isinstance(value, ast.Dict):
            self.keys.update(self._dict_keys(value))
        elif isinstance(value, ast.Name) and value.id in self.vars:
            self.keys.update(self.vars[value.id])
            self.keys.update(self.dict_writes.get(value.id, set()))


def _functions_in(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _returned_keys_for(path: Path, names: set[str]) -> set[str]:
    """Union of returned top-level keys for the given functions in a file."""
    funcs = _functions_in(path)
    keys: set[str] = set()
    for name in names:
        fn = funcs.get(name)
        if fn is None:
            continue
        vis = _ReturnKeys()
        vis.visit(fn)
        keys |= vis.keys
    return keys


def collect_returned_keys() -> set[str]:
    """Audit all active node entry points (+ delegation chains) and runner."""
    keys: set[str] = set()
    for rel, names in NODE_FILES.items():
        keys |= _returned_keys_for(ROOT / rel, names)
    for rel, callee_names in BUILD_CALLEES.items():
        keys |= _returned_keys_for(ROOT / rel, callee_names)
    return keys


def test_schema_keys_are_returned_or_input_only():
    """Every WorkflowState key must be node-returned or on INPUT_ONLY_KEYS."""
    from graph.state import INPUT_ONLY_KEYS, WorkflowState

    declared = set(WorkflowState.__annotations__)
    returned = collect_returned_keys()
    orphans = declared - returned - INPUT_ONLY_KEYS
    assert not orphans, (
        f"WorkflowState keys neither returned by any active node nor listed in "
        f"INPUT_ONLY_KEYS: {sorted(orphans)}. If a key is truly dead, delete it "
        f"from the schema; if it is input-seeded, add it to INPUT_ONLY_KEYS."
    )


def test_input_only_keys_declared_in_schema():
    """Every INPUT_ONLY_KEYS entry must be a declared WorkflowState key."""
    from graph.state import INPUT_ONLY_KEYS, WorkflowState

    declared = set(WorkflowState.__annotations__)
    missing = INPUT_ONLY_KEYS - declared
    assert not missing, (
        f"INPUT_ONLY_KEYS entries not declared in WorkflowState: {sorted(missing)}. "
        f"Declare them in graph/state.py (or drop them from INPUT_ONLY_KEYS)."
    )


def test_input_only_keys_are_frozenset_of_str():
    """INPUT_ONLY_KEYS must be a frozenset of str."""
    from graph.state import INPUT_ONLY_KEYS

    assert isinstance(INPUT_ONLY_KEYS, frozenset)
    assert all(isinstance(k, str) for k in INPUT_ONLY_KEYS)


def test_no_node_returns_undeclared_state_keys():
    """Nodes must not return top-level keys absent from the schema.

    LangGraph silently tolerates unknown keys at runtime, so this is the
    structural check that the schema stays the single source of truth.
    """
    from graph.state import WorkflowState

    declared = set(WorkflowState.__annotations__)
    returned = collect_returned_keys()
    # Helper-scan noise: _scan_codebase returns a non-state scan dict; those
    # keys are never state keys and are excluded from the node audit set.
    SCAN_KEYS = {
        "branch", "tree", "routes", "models", "docker", "git", "project_type",
        "specs", "templates", "dependencies",
    }
    undeclared = returned - declared - SCAN_KEYS
    assert not undeclared, (
        f"Nodes return top-level keys not declared in WorkflowState: "
        f"{sorted(undeclared)}. Add them to the schema or stop returning them."
    )


def test_deleted_dead_keys_gone_from_schema():
    """The P0-A1 audit-confirmed dead keys must not remain in the schema."""
    from graph.state import WorkflowState

    declared = set(WorkflowState.__annotations__)
    dead = {
        "tasks", "tasks_text", "backlog", "solution_md", "plan",
        "status", "retry_count", "spec_text", "spec_refined",
        "project_context", "diagram_pngs", "superweb_agent_report",
    }
    leftovers = declared & dead
    assert not leftovers, (
        f"Dead keys still declared in WorkflowState: {sorted(leftovers)}"
    )


def test_schema_key_count_shrunk():
    """After the trim the schema is 29 keys (41 - 12 deleted)."""
    from graph.state import WorkflowState

    assert len(WorkflowState.__annotations__) == 29


@pytest.mark.parametrize(
    "input_only_key",
    [
        "skip_discover", "improve_mode", "force_hil", "auto_approve_override",
        "arckit_artifacts", "trace_id", "cycle_id", "config_version",
    ],
)
def test_input_only_keys_present(input_only_key):
    from graph.state import INPUT_ONLY_KEYS

    assert input_only_key in INPUT_ONLY_KEYS
