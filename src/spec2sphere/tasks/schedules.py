import os

from celery.schedules import crontab

# Beat schedules — loaded into celery_app.conf.beat_schedule
BEAT_SCHEDULE = {
    "nightly-qa": {
        "task": "spec2sphere.tasks.agent_tasks.run_qa_check",
        "schedule": crontab(hour=2, minute=0),
        "kwargs": {"object_id": "all", "config_path": "config.yaml"},
        "options": {"priority": 5},
    },
    "weekly-report": {
        "task": "spec2sphere.tasks.agent_tasks.run_report_generator",
        "schedule": crontab(day_of_week=1, hour=6, minute=0),
        "kwargs": {"scope": "all", "config_path": "config.yaml"},
        "options": {"priority": 5},
    },
}

# Optional periodic re-scan controlled by env var
# Set SCAN_CRON_SCHEDULE to enable (e.g. "0 3 * * *" for 3am daily)
# TODO: implement full cron string parsing when needed

# File Drop polling — every 5 minutes, only when FILE_DROP_ENABLED=true
if os.environ.get("FILE_DROP_ENABLED", "false").lower() == "true":
    BEAT_SCHEDULE["file-drop-poll"] = {
        "task": "spec2sphere.tasks.file_drop_tasks.poll_drop_directory",
        "schedule": 300,  # seconds
        "options": {"priority": 3},
    }

# M365 Copilot Graph Connector sync — every 4 hours.
# Task silently skips when M365_* env vars are not configured.
BEAT_SCHEDULE["m365-graph-sync"] = {
    "task": "spec2sphere.tasks.m365_sync.sync_m365_graph_index",
    "schedule": crontab(minute=0, hour="*/4"),
    "kwargs": {"incremental": False},
    "options": {"priority": 3},
}


# dsp-ai morning briefing batch — configurable cron via BATCH_CRON.
# Default: 06:00 on weekdays. Parsed from a 5-field cron string.
def _crontab_from_env(var: str, default: str) -> crontab:
    fields = (os.environ.get(var) or default).strip().split()
    if len(fields) != 5:
        fields = default.split()
    minute, hour, day_of_month, month_of_year, day_of_week = fields
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


BEAT_SCHEDULE["dsp-ai-batch-morning"] = {
    "task": "spec2sphere.dsp_ai.run_batch_enhancements",
    "schedule": _crontab_from_env("BATCH_CRON", "0 6 * * 1-5"),
    "options": {"priority": 5, "queue": "ai-batch"},
}
