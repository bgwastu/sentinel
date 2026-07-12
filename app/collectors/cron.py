from __future__ import annotations

import datetime as _datetime
import time

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

def _recent_log_lines() -> list[str]:
    """Read host cron logs without executing job commands.

    Syslog/journald access varies by image; an empty list is an honest
    unavailable state rather than fabricated run history.
    """
    lines: list[str] = []
    for relative in ("var/log/cron", "var/log/cron.log", "var/log/syslog"):
        path = host_path(relative)
        try:
            if path.exists() and path.is_file():
                lines.extend(path.read_text(errors="ignore").splitlines()[-500:])
        except OSError:
            continue
    return lines


def _job_history(command: str, lines: list[str]) -> list[dict]:
    now = time.time()
    token = command.strip().split()[0].rsplit("/", 1)[-1] if command.strip() else ""
    if not token:
        return []
    runs: list[dict] = []
    timestamp_pattern = re.compile(r"([A-Z][a-z]{2}\s+\d{1,2}\s+\d\d:\d\d:\d\d)")
    for line in reversed(lines):
        if token not in line and command[:48] not in line:
            continue
        stamp = timestamp_pattern.search(line)
        if not stamp:
            continue
        try:
            parsed = _datetime.datetime.strptime(
                f"{_datetime.datetime.now().year} {stamp.group(1)}",
                "%Y %b %d %H:%M:%S",
            ).timestamp()
        except ValueError:
            continue
        if now - parsed > 4 * 60 * 60 or parsed > now + 60:
            continue
        runs.append({"timestamp": parsed, "message": line.strip()})
        if len(runs) == 3:
            break
    return runs


def _attach_history(jobs: list[dict]) -> list[dict]:
    lines = _recent_log_lines()
    for job in jobs:
        history = _job_history(job["command"], lines)
        job["last_runs"] = history
        job["log_available"] = bool(lines)
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

    return _attach_history(jobs)
