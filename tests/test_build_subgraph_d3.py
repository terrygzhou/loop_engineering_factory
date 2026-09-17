"""D3: retry_count must reset when advancing backlog_idx on exhaustion."""
import graph.nodes.build_subgraph_legacy as bg


def _substate_at_implement(tmp_path, item_id="1", retry_count=2, backlog_len=2):
    """Build a minimal BuildSubState at the IMPLEMENT sub-phase."""
    items = []
    for i in range(1, backlog_len + 1):
        items.append(
            {
                "id": str(i),
                "description": f"Item {i}",
                "status": "pending" if i > 1 else "in_progress",
            }
        )
    return {
        "sub_phase": "IMPLEMENT",
        "project_path": str(tmp_path),
        "docker_proj": str(tmp_path),
        "spec_text": "A test spec",
        "tasks_text": "Task list",
        "skills": {
            "incremental-implementation": {"content": "Stub skill"},
            "test-driven-development": {"content": "Stub TDD skill"},
        },
        "backlog": items,
        "backlog_idx": 0,
        "impl_plan": "",
        "current_code": "",
        "test_code": "",
        "test_result": "",
        "test_output": "",
        "retry_count": retry_count,
        "int_test_result": "",
        "int_test_output": "",
        "seed_result": "",
        "seed_output": "",
        "uat_result": "",
        "uat_output": "",
        "uat_pass_rate": 0.5,
        "all_generated_code": [],
        "errors": [],
        "build_status": "pending",
        "parent_artifacts": {},
        "superweb_mode": "agent",
        "superweb_agent_report": {},
        "security_review": "",
        "code_review": "",
    }


def test_no_code_exhaustion_resets_retry_for_next_item(monkeypatch, tmp_path):
    """When item 1 exhausts its retry budget on a no-code failure,
    retry_count must reset to 0 so item 2 gets a fresh budget."""
    state = _substate_at_implement(
        tmp_path,
        item_id="1",
        retry_count=2,  # at max_item_retries - 1 = 2 (bounds.build.max_item_retries = 3)
        backlog_len=2,
    )
    # invoke_skill is imported at module level (`from tools.llm import
    # invoke_skill`), so monkeypatch it on the bg module, not tools.llm.
    #
    # implement_node's no-code path: `item_code` is assigned the result of
    # invoke_skill(...) and the failure branch triggers on
    # `if not item_code:` — i.e. an empty-string result drives it.
    monkeypatch.setattr(bg, "invoke_skill", lambda *a, **k: "")
    out = bg.implement_node(state)
    assert out["backlog_idx"] == 1
    assert out["retry_count"] == 0
