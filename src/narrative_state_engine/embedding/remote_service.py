from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteEmbeddingServiceConfig:
    ssh_host: str = "zjgGroup-A800"
    service_dir: str = "/home/data/nas_hdd/jinglong/waf/novel-embedding-service"
    base_url: str = "http://172.18.36.87:18080"
    cuda_visible_devices: str = "6"
    startup_timeout_s: int = 420
    poll_interval_s: float = 3.0

    @classmethod
    def from_env(cls, *, base_url: str | None = None) -> "RemoteEmbeddingServiceConfig":
        return cls(
            ssh_host=os.getenv("NOVEL_AGENT_REMOTE_EMBEDDING_SSH_HOST", cls.ssh_host),
            service_dir=os.getenv("NOVEL_AGENT_REMOTE_EMBEDDING_SERVICE_DIR", cls.service_dir),
            base_url=(base_url or os.getenv("NOVEL_AGENT_VECTOR_STORE_URL") or cls.base_url).rstrip("/"),
            cuda_visible_devices=os.getenv("NOVEL_AGENT_REMOTE_EMBEDDING_CUDA_DEVICES", cls.cuda_visible_devices),
            startup_timeout_s=int(os.getenv("NOVEL_AGENT_REMOTE_EMBEDDING_STARTUP_TIMEOUT_S", str(cls.startup_timeout_s))),
            poll_interval_s=float(os.getenv("NOVEL_AGENT_REMOTE_EMBEDDING_POLL_INTERVAL_S", str(cls.poll_interval_s))),
        )


class RemoteEmbeddingServiceManager:
    def __init__(self, config: RemoteEmbeddingServiceConfig | None = None) -> None:
        self.config = config or RemoteEmbeddingServiceConfig.from_env()
        self.started_by_manager = False

    def ensure_running(self) -> None:
        if self.is_healthy():
            return
        self.start()
        deadline = time.monotonic() + self.config.startup_timeout_s
        while time.monotonic() < deadline:
            if self.is_healthy():
                return
            time.sleep(self.config.poll_interval_s)
        raise TimeoutError(
            f"Remote embedding service did not become healthy within "
            f"{self.config.startup_timeout_s}s: {self.config.base_url}"
        )

    def start(self) -> None:
        script = (
            f"cd {self.config.service_dir} && "
            f"CUDA_VISIBLE_DEVICES={self.config.cuda_visible_devices} ./run_server.sh"
        )
        self._ssh(script)
        self.started_by_manager = True

    def stop(self) -> None:
        script = f"cd {self.config.service_dir} && ./stop_server.sh"
        self._ssh(script, check=False)

    def is_healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.config.base_url}/health", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return str(payload.get("status", "")).lower() == "ok"
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    def _ssh(self, remote_script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", self.config.ssh_host, remote_script],
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
