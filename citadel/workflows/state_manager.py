# citadel/workflows/state_manager.py

import json
from datetime import datetime


class WorkflowStateManager:
    def __init__(self, db):
        self.db = db

    async def load(self, session_id: str) -> dict | None:
        result = await self.db.execute(
            "SELECT workflow_kind, step, data FROM workflow_state WHERE session_id = ?",
            (session_id,)
        )
        if not result:
            return None
        kind, step, data_json = result[0]
        return {
            "workflow": kind,
            "step": step,
            "data": json.loads(data_json)
        }

    async def save(self, session_id: str, workflow: str, step: int, data: dict):
        await self.db.execute(
            "INSERT OR REPLACE INTO workflow_state (session_id, workflow_kind, step, data) VALUES (?, ?, ?, ?)",
            (session_id, workflow, step, json.dumps(data))
        )

    async def delete(self, session_id: str):
        await self.db.execute(
            "DELETE FROM workflow_state WHERE session_id = ?",
            (session_id,)
        )
