import os
from pathlib import Path

HOST_PREFIX = Path(os.environ.get("HOST_PREFIX", "/host"))
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PORT = int(os.environ.get("PORT", "8080"))
STORAGE_SCAN_INTERVAL = int(os.environ.get("STORAGE_SCAN_INTERVAL", "3600"))
HISTORY_SIZE = 15
SPARKLINE_INTERVAL = float(os.environ.get("SPARKLINE_INTERVAL", "2.0"))

SCAN_DIRECTORIES = [
    "/var/lib/docker",
    "/var/log",
    "/home",
    "/usr/share",
    "/var/www",
    "/opt",
    "/etc",
    "/tmp",
]

IGNORED_FS_TYPES = {
    "proc",
    "sysfs",
    "devtmpfs",
    "devfs",
    "tmpfs",
    "overlay",
    "squashfs",
    "cgroup",
    "cgroup2",
    "securityfs",
    "pstore",
    "bpf",
    "tracefs",
    "debugfs",
    "hugetlbfs",
    "mqueue",
    "configfs",
    "fusectl",
    "autofs",
    "binfmt_misc",
}

VIRTUAL_MOUNT_PREFIXES = ("/proc", "/sys", "/dev", "/run")
