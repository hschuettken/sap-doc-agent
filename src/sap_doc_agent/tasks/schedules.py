from celery.schedules import crontab

# Beat schedules — loaded into celery_app.conf.beat_schedule
BEAT_SCHEDULE = {
    "nightly-qa": {
        "task": "sap_doc_agent.tasks.agent_tasks.run_qa_check",
        "schedule": crontab(hour=2, minute=0),
        "kwargs": {"object_id": "all", "config_path": "config.yaml"},
        "options": {"priority": 5},
    },
    "weekly-report": {
        "task": "sap_doc_agent.tasks.agent_tasks.run_report_generator",
        "schedule": crontab(day_of_week=1, hour=6, minute=0),
        "kwargs": {"scope": "all", "config_path": "config.yaml"},
        "options": {"priority": 5},
    },
}

# Optional periodic re-scan controlled by env var
# Set SCAN_CRON_SCHEDULE to enable (e.g. "0 3 * * *" for 3am daily)
# TODO: implement full cron string parsing when needed
