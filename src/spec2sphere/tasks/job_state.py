import json
import time
from typing import Optional

JOB_PREFIX = "sapdoc:job:"
JOB_TTL = 86400  # 24 hours


class JobState:
    def __init__(self, redis_client):
        self._r = redis_client

    def register(self, task_id: str, job_type: str, params: dict) -> None:
        data = {
            "task_id": task_id,
            "job_type": job_type,
            "params": params,
            "status": "queued",
            "created_at": time.time(),
        }
        self._r.setex(f"{JOB_PREFIX}{task_id}", JOB_TTL, json.dumps(data))

    def get(self, task_id: str) -> Optional[dict]:
        raw = self._r.get(f"{JOB_PREFIX}{task_id}")
        return json.loads(raw) if raw else None

    def update_status(self, task_id: str, status: str, result: Optional[dict] = None) -> None:
        data = self.get(task_id)
        if data:
            data["status"] = status
            if result:
                data["result"] = result
            self._r.setex(f"{JOB_PREFIX}{task_id}", JOB_TTL, json.dumps(data))

    def list_recent(self, limit: int = 50) -> list[dict]:
        keys = self._r.keys(f"{JOB_PREFIX}*")
        jobs = []
        for k in keys:
            raw = self._r.get(k)
            if raw:
                jobs.append(json.loads(raw))
        return sorted(jobs, key=lambda j: j.get("created_at", 0), reverse=True)[:limit]
