from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Dict, List


DEFAULT_ENTRIES = [
    {
        "title": "VTS标准通信用语",
        "category": "VTS通信",
        "source": "2025《船舶交通管理（VTS）标准通信用语指南》",
        "content": "船舶与VTS通信应采用简明、规范、可确认的标准用语，涉及航行动态和险情时应明确报告船名、船位、事件类型及所需协助。",
    },
    {
        "title": "险情优先处置",
        "category": "应急处置",
        "source": "VTS业务规则",
        "content": "遇到碰撞、搁浅、火灾爆炸、进水、沉没、人员落水和失控等险情，应优先人工接管，核实船位、人员和周边通航态势。",
    },
    {
        "title": "常规报告自动回复边界",
        "category": "自动处置",
        "source": "数字值班员MVP规则",
        "content": "自动回复仅用于靠泊、锚泊、过报告线等规则明确的由动转静报告。离泊、出港、穿越警戒区和高危情况必须转人工确认。",
    },
]


class KnowledgeRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.docs_dir = data_dir / "knowledge_documents"
        self.index_path = data_dir / "knowledge_index.json"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self._entries = self._load_or_seed()

    def list_entries(self) -> List[Dict[str, str]]:
        return list(self._entries)

    def search(self, query: str) -> List[Dict[str, str]]:
        needle = query.strip().lower()
        if not needle:
            return self.list_entries()
        scored = []
        for entry in self._entries:
            haystack = " ".join(str(value) for value in entry.values()).lower()
            score = sum(haystack.count(token) for token in needle.split() if token)
            if needle in haystack:
                score += 3
            if score:
                scored.append((score, entry))
        return [entry for _, entry in sorted(scored, key=lambda item: item[0], reverse=True)]

    def import_document(self, source: BinaryIO, filename: str, category: str = "法规资料") -> Dict[str, str]:
        suffix = Path(filename).suffix.lower()
        target = self.docs_dir / f"{uuid.uuid4().hex[:12]}{suffix or '.bin'}"
        with target.open("wb") as output:
            shutil.copyfileobj(source, output)
        content = self._extract_text(target)
        entry = {
            "id": f"kb_{uuid.uuid4().hex[:12]}",
            "title": Path(filename).stem,
            "category": category.strip() or "法规资料",
            "source": filename,
            "content": content[:12_000] or "文档已导入，当前环境未能自动抽取正文。",
            "file_path": str(target),
        }
        self._entries.append(entry)
        self._save()
        return entry

    def _load_or_seed(self) -> List[Dict[str, str]]:
        if self.index_path.exists():
            try:
                rows = json.loads(self.index_path.read_text(encoding="utf-8"))
                if isinstance(rows, list) and rows:
                    return rows
            except Exception:
                pass
        rows = [
            {"id": f"kb_seed_{index}", **entry}
            for index, entry in enumerate(DEFAULT_ENTRIES, start=1)
        ]
        self._entries = rows
        self._save()
        return rows

    def _save(self) -> None:
        self.index_path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_text(path: Path) -> str:
        if path.suffix.lower() in {".txt", ".md", ".json", ".csv"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader

                return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
            except Exception:
                return ""
        return ""
