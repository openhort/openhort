"""Disk Usage — monitors partition usage across all mountpoints."""

from __future__ import annotations

import asyncio
import time

from hort.llming import Llming, power, on, PowerInput, PowerOutput, PulseEvent


# ── Data models ──


class PartitionInfo(PowerOutput):
    version: int = 1
    device: str = ""
    mountpoint: str = ""
    fstype: str = ""
    total_gb: float = 0
    used_gb: float = 0
    free_gb: float = 0
    percent: float = 0


class DiskUsageResponse(PowerOutput):
    version: int = 1
    partitions: list[dict] = []
    timestamp: float = 0


class PartitionRequest(PowerInput):
    version: int = 1
    mountpoint: str = "/"


class DiskUpdate(PulseEvent):
    """Emitted on every poll with current partition data."""
    version: int = 1
    partitions: list[dict] = []
    timestamp: float = 0


# ── Llming ──


class DiskUsage(Llming):
    """Monitors disk partitions and stores usage data."""

    _latest: dict = {}

    def activate(self, config: dict) -> None:
        self._latest = {}
        self.log.info("Disk usage monitor activated")

    @on("tick:slow")
    async def poll_disks(self, _data: dict) -> None:
        """Poll disk partitions every 5s via tick:slow channel."""
        partitions = await asyncio.to_thread(self._read_partitions)
        now = time.time()

        self._latest = {"timestamp": now, "partitions": partitions}
        self.vault.set("state", self._latest)
        await self.emit("disk_usage", DiskUpdate(partitions=partitions, timestamp=now))

    @power("get_disk_usage")
    async def get_disk_usage(self) -> DiskUsageResponse:
        """Get disk usage for all partitions."""
        if not self._latest:
            return DiskUsageResponse(code=404, message="No disk data available yet")
        return DiskUsageResponse(
            partitions=self._latest.get("partitions", []),
            timestamp=self._latest.get("timestamp", 0),
        )

    @power("get_partition_details")
    async def get_partition_details(self, req: PartitionRequest) -> PartitionInfo:
        """Get detailed usage info for a specific partition by mountpoint."""
        if not self._latest:
            return PartitionInfo(code=404, message="No disk data available yet")
        for p in self._latest.get("partitions", []):
            if p["mountpoint"] == req.mountpoint:
                return PartitionInfo(**p)
        available = ", ".join(p["mountpoint"] for p in self._latest.get("partitions", []))
        return PartitionInfo(code=404, message=f"'{req.mountpoint}' not found. Available: {available}")

    @power("disk", command=True)
    async def disk_command(self) -> str:
        """Show disk usage summary for all partitions."""
        if not self._latest:
            return "No disk data available yet."
        lines = []
        for p in self._latest.get("partitions", []):
            lines.append(f"{p['mountpoint']}: {p['used_gb']}/{p['total_gb']} GB ({p['percent']}%)")
        return "\n".join(lines) if lines else "No partitions found."

    def get_pulse(self) -> dict:
        """UI thumbnail data."""
        return {"latest": self._latest}

    @staticmethod
    def _read_partitions() -> list[dict]:
        import psutil

        partitions = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent": usage.percent,
            })
        return partitions
