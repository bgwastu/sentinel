from __future__ import annotations

import re
from pathlib import Path

from app.utils import host_path

CRON_LINE = re.compile(
    r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(\S+)\s+(.+)$"
)
CRON_USER_LINE = re.compile(
    r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(\S+)\s+(.+)$"
)


def _describe_frequency(schedule: str) -> str:
    parts = schedule.split()
    if len(parts) != 5:
        return "Custom schedule"

    minute, hour, dom, month, dow = parts

    if schedule == "* * * * *":
        return "Every minute"
    if minute.startswith("*/"):
        try:
            interval = int(minute[2:])
            return f"Every {interval} minutes"
        except ValueError:
            pass
    if minute == "0" and hour == "*":
        return "Every hour"
    if minute == "0" and hour != "*" and dom == "*" and month == "*" and dow == "*":
        try:
            h = int(hour)
            suffix = "AM" if h < 12 else "PM"
            display = h if h <= 12 else h - 12
            if display == 0:
                display = 12
            return f"Daily at {display}:00 {suffix}"
        except ValueError:
            return f"Daily at hour {hour}"
    if dom == "1" and month == "*" and dow == "*":
        return "First day of each month"
    if dow != "*" and dom == "*":
        days = {
            "0": "Sunday",
            "1": "Monday",
            "2": "Tuesday",
            "3": "Wednesday",
            "4": "Thursday",
            "5": "Friday",
            "6": "Saturday",
            "7": "Sunday",
        }
        return f"Weekly on {days.get(dow, dow)}"
    if hour == "*" and minute != "*":
        return f"Hourly at minute {minute}"
    return "Custom schedule"


def _parse_line(line: str, default_user: str = "root") -> dict | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("SHELL=") or stripped.startswith("PATH="):
        return None
    if stripped.startswith("@"):
        return None

    match = CRON_USER_LINE.match(stripped)
    if not match:
        return None

    schedule, user, command = match.groups()
    if schedule.count(" ") != 4:
        return None

    return {
        "schedule": schedule,
        "user": user or default_user,
        "command": command.strip(),
        "frequency": _describe_frequency(schedule),
    }


def _read_file(path: Path, default_user: str = "root") -> list[dict]:
    jobs: list[dict] = []
    try:
        if not path.exists():
            return jobs
        for line in path.read_text(errors="ignore").splitlines():
            entry = _parse_line(line, default_user=default_user)
            if entry:
                jobs.append(entry)
    except OSError:
        pass
    return jobs


def collect_cron() -> list[dict]:
    jobs: list[dict] = []

    jobs.extend(_read_file(host_path("etc/crontab")))

    cron_d = host_path("etc/cron.d")
    if cron_d.exists():
        for path in sorted(cron_d.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                jobs.extend(_read_file(path))

    spool = host_path("var/spool/cron/crontabs")
    if spool.exists():
        for path in sorted(spool.iterdir()):
            if path.is_file():
                user = path.name
                for line in path.read_text(errors="ignore").splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    parts = stripped.split(None, 5)
                    if len(parts) >= 6:
                        schedule = " ".join(parts[:5])
                        command = parts[5]
                        jobs.append(
                            {
                                "schedule": schedule,
                                "user": user,
                                "command": command,
                                "frequency": _describe_frequency(schedule),
                            }
                        )
                    elif len(parts) == 6:
                        pass

    # macOS / some systems use /var/spool/cron without crontabs subdir
    spool_alt = host_path("var/spool/cron")
    if spool_alt.exists() and spool_alt.name != "crontabs":
        for path in sorted(spool_alt.iterdir()):
            if path.is_file() and path.name not in {".", ".."}:
                user = path.name
                try:
                    for line in path.read_text(errors="ignore").splitlines():
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        parts = stripped.split(None, 5)
                        if len(parts) >= 6:
                            schedule = " ".join(parts[:5])
                            command = parts[5]
                            jobs.append(
                                {
                                    "schedule": schedule,
                                    "user": user,
                                    "command": command,
                                    "frequency": _describe_frequency(schedule),
                                }
                            )
                except OSError:
                    continue

    return jobs
