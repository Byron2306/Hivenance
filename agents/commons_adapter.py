from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from agents.data_store_agent import DataStoreAgent


@dataclass
class CommonsAdapterResult:
    file_path: str
    status: str
    receipt_kind: Optional[str] = None
    receipt_id: Optional[str] = None
    adoption_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "status": self.status,
            "receipt_kind": self.receipt_kind,
            "receipt_id": self.receipt_id,
            "adoption_id": self.adoption_id,
            "error": self.error,
        }


class CommonsAdapter:
    def __init__(self, data_store: DataStoreAgent, *, inbox_dir: Path, archive_dir: Path) -> None:
        self.data_store = data_store
        self.inbox_dir = Path(inbox_dir)
        self.archive_dir = Path(archive_dir)
        self.success_dir = self.archive_dir / "accepted"
        self.error_dir = self.archive_dir / "rejected"

    def ensure_directories(self) -> None:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.success_dir.mkdir(parents=True, exist_ok=True)
        self.error_dir.mkdir(parents=True, exist_ok=True)

    def process_once(self) -> Dict[str, Any]:
        self.ensure_directories()
        files = sorted(
            [
                path for path in self.inbox_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".json"
            ],
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        results = [self.process_file(path).to_dict() for path in files]
        return {
            "processed": len(results),
            "accepted": sum(1 for row in results if row.get("status") == "accepted"),
            "rejected": sum(1 for row in results if row.get("status") == "rejected"),
            "results": results,
        }

    def process_file(self, path: Path) -> CommonsAdapterResult:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            result = CommonsAdapterResult(
                file_path=str(path),
                status="rejected",
                error=f"invalid_json:{type(exc).__name__}:{exc}",
            )
            self._move_to_error(path, result.to_dict())
            return result

        try:
            receipts = list(self._normalize_receipts(payload))
            if not receipts:
                raise ValueError("no_receipts_found")
            results = [self._ingest_receipt(path, receipt) for receipt in receipts]
            accepted = next((row for row in results if row.status == "accepted"), results[0])
            self._move_to_success(path, {"results": [row.to_dict() for row in results]})
            return CommonsAdapterResult(
                file_path=str(path),
                status="accepted",
                receipt_kind=accepted.receipt_kind,
                receipt_id=accepted.receipt_id,
                adoption_id=accepted.adoption_id,
            )
        except Exception as exc:
            result = CommonsAdapterResult(
                file_path=str(path),
                status="rejected",
                error=f"{type(exc).__name__}:{exc}",
            )
            self._move_to_error(path, result.to_dict())
            return result

    def _normalize_receipts(self, payload: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("receipts"), list):
                for item in payload.get("receipts") or []:
                    if isinstance(item, dict):
                        yield item
                return
            yield payload
            return
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item

    def _ingest_receipt(self, path: Path, receipt: Dict[str, Any]) -> CommonsAdapterResult:
        receipt_kind = self._detect_receipt_kind(receipt)
        if receipt_kind == "inference":
            adoption = self.data_store.ingest_commons_inference_packet(receipt)
        elif receipt_kind == "verifier":
            adoption = self.data_store.ingest_commons_verifier_packet(receipt)
        else:
            raise ValueError("unsupported_receipt_kind")
        if not isinstance(adoption, dict):
            raise ValueError("adoption_receipt_missing")
        return CommonsAdapterResult(
            file_path=str(path),
            status="accepted",
            receipt_kind=receipt_kind,
            receipt_id=str(receipt.get("receipt_id") or ""),
            adoption_id=str(adoption.get("adoption_id") or ""),
        )

    def _detect_receipt_kind(self, receipt: Dict[str, Any]) -> str:
        schema = str(receipt.get("schema") or "").lower()
        receipt_type = str(receipt.get("receipt_type") or receipt.get("kind") or "").lower()
        if "inference" in schema or receipt_type == "inference":
            return "inference"
        if "verifier" in schema or receipt_type == "verifier":
            return "verifier"
        if "verification_verdict" in receipt:
            return "verifier"
        if {"receipt_id", "task_class", "phase_scope"}.issubset(set(receipt.keys())):
            return "inference"
        return "unknown"

    def _move_to_success(self, source: Path, metadata: Dict[str, Any]) -> None:
        self._move_with_manifest(source, self.success_dir, metadata)

    def _move_to_error(self, source: Path, metadata: Dict[str, Any]) -> None:
        self._move_with_manifest(source, self.error_dir, metadata)

    def _move_with_manifest(self, source: Path, target_dir: Path, metadata: Dict[str, Any]) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"{source.stem}-{timestamp}{source.suffix}"
        shutil.move(str(source), str(target))
        manifest_path = target.with_suffix(f"{target.suffix}.result.json")
        manifest_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
