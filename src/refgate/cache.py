from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re


@dataclass
class RawRecord:
    source: str
    url: str
    status: int
    headers: dict[str, str]
    body: str
    fetched_at: str

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["body_sha256"] = self.body_sha256
        return data


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cache_key(url: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", url).strip("_")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{safe[:120]}_{digest}.json"


def raw_record_path(source: str, url: str, cache_root: str | Path = ".refgate/cache") -> Path:
    return Path(cache_root) / source / cache_key(url)


def write_raw_record(record: RawRecord, cache_root: str | Path = ".refgate/cache") -> Path:
    target_dir = Path(cache_root) / record.source
    target_dir.mkdir(parents=True, exist_ok=True)
    target = raw_record_path(record.source, record.url, cache_root=cache_root)
    target.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def read_raw_record(source: str, url: str, cache_root: str | Path = ".refgate/cache") -> RawRecord | None:
    target = raw_record_path(source, url, cache_root=cache_root)
    if not target.exists():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    return RawRecord(
        source=data["source"],
        url=data["url"],
        status=int(data["status"]),
        headers={str(key): str(value) for key, value in data.get("headers", {}).items()},
        body=data["body"],
        fetched_at=data["fetched_at"],
    )
