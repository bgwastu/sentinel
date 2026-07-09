from __future__ import annotations

import os
from pathlib import Path

HOST_PREFIX = Path(os.environ.get("HOST_PREFIX", "/host"))
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PORT = int(os.environ.get("PORT", "8080"))
STORAGE_SCAN_INTERVAL = int(os.environ.get("STORAGE_SCAN_INTERVAL", "3600"))
HISTORY_SIZE = 15
SPARKLINE_INTERVAL = float(os.environ.get("SPARKLINE_INTERVAL", "2.0"))
HISTORY_PATH = Path(os.environ.get("HISTORY_PATH", "/tmp/sentinel-history.json"))
PROCESS_MAX_NODES = int(os.environ.get("PROCESS_MAX_NODES", "250"))
PROCESS_MAX_DEPTH = int(os.environ.get("PROCESS_MAX_DEPTH", "10"))
PROCESS_MAX_ROOTS = int(os.environ.get("PROCESS_MAX_ROOTS", "40"))

SYSTEM_NAME_PREFIXES = (
    "kworker",
    "ksoftirq",
    "migration",
    "cpuhp",
    "idle_inject",
    "rcu_",
    "irq/",
    "pool_",
    "slub_",
    "mm_percpu",
    "inet_frag",
    "writeback",
    "kstrp",
    "acpi_",
    "scsi_",
    "md",
    "raid",
    "jbd2",
    "ext4",
    "xfs",
)

SYSTEM_PROCESS_NAMES = {
    "systemd",
    "kthreadd",
    "init",
    "rpcbind",
    "cupsd",
    "master",
    "dbus-daemon",
    "systemd-journald",
    "systemd-logind",
    "systemd-udevd",
    "systemd-resolved",
    "systemd-networkd",
    "systemd-timesyncd",
    "multipathd",
    "rsyslogd",
    "cron",
    "atd",
    "agetty",
    "polkitd",
    "unattended-upgrade",
    "accounts-daemon",
    "ModemManager",
    "udisksd",
    "upowerd",
    "chronyd",
    "monit",
    "sshd",
    "containerd",
    "containerd-shim",
    "dockerd",
    "docker-proxy",
    "rpc.mountd",
    "rpc.statd",
    "rpc.idmapd",
    "rpc.gssd",
    "gssproxy",
    "simplevisor",
}

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
