from simple_agent.oss_runtime import _pinned_instruction_context


class FakeDb:
    def __init__(self):
        self.snapshot = None
        self.writes = 0

    def execute(self, sql, values):
        if sql.startswith("SELECT"):
            assert values == ("thread-c6",)
        else:
            assert "SET instruction_snapshot" in sql
            assert values[1] == "thread-c6"
            self.snapshot = values[0].obj
            self.writes += 1
        return self

    def fetchone(self):
        return {"instruction_snapshot": self.snapshot}


def test_instruction_snapshot_is_pinned_without_freezing_other_settings():
    db = FakeDb()
    initial = {
        "system_prompt": "C6 v1",
        "agent_instructions": "Regras v1",
        "active_workflow": "Fluxo v1",
        "agent_profile": {"name": "Sophia"},
        "allowed_tools": ["okf_index"],
    }
    assert _pinned_instruction_context(db, "thread-c6", initial) == initial
    updated = {
        **initial,
        "system_prompt": "C6 v2",
        "agent_instructions": "Regras v2",
        "active_workflow": "Fluxo v2",
        "allowed_tools": [],
    }
    effective = _pinned_instruction_context(db, "thread-c6", updated)
    assert [effective[key] for key in ("system_prompt", "agent_instructions", "active_workflow")] == [
        "C6 v1", "Regras v1", "Fluxo v1"
    ]
    assert effective["allowed_tools"] == []
    assert db.writes == 1
