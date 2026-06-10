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
    {
        "title": "COLREG避碰责任",
        "category": "IMO规范",
        "source": "1972年国际海上避碰规则（COLREG）",
        "content": "船舶应始终保持正规瞭望，使用安全航速，并根据会遇态势及时采取明显、有效且留有充分余地的避让行动。",
    },
    {
        "title": "SOLAS遇险通信",
        "category": "IMO规范",
        "source": "SOLAS公约与GMDSS遇险通信要求",
        "content": "涉及火灾、碰撞、进水、人员落水、失控等紧急情况时，应优先处理遇险通信，核实船名、船位、险情性质、人员状态和所需协助。",
    },
    {
        "title": "离泊与关键动态人工确认",
        "category": "VTS业务",
        "source": "VTS值班业务规则",
        "content": "离泊、出港、穿越重点水域和航行计划变更涉及实时交通态势，应进入人工确认流程，不由系统直接自动批准。",
    },
    {
        "title": "船舶报告适用范围",
        "category": "VTS报告规则",
        "source": "船舶报告与引航业务材料",
        "content": "适用船舶包括外国籍船舶，以及客船、危险品船舶、拖带船队、操纵能力受限船舶、参与水上水下活动和港区安全作业船舶、涉污作业船舶、影响通航安全船舶，以及300总吨及以上的其他中国籍船舶。",
    },
    {
        "title": "抵港与靠泊报告",
        "category": "VTS报告规则",
        "source": "船舶报告与引航业务材料",
        "content": "船舶抛锚、靠泊前15分钟报告；抛妥锚、靠妥码头后立即报告。报告内容包括船名、船舶动态、锚位、出链长度、靠泊位置等。抛锚报告、靠妥报告可作为常规报告自动回复候选。",
    },
    {
        "title": "开航离泊报告",
        "category": "VTS报告规则",
        "source": "船舶报告与引航业务材料",
        "content": "船舶离泊或起锚前15分钟报告，内容包括船名、离泊或起锚时间及目的地。涉及申请、准备、离泊、起锚、备车、开航、解缆等意图时，应进入人工审核。",
    },
    {
        "title": "事故与异常情况报告",
        "category": "VTS报告规则",
        "source": "船舶报告与引航业务材料",
        "content": "船舶发生影响交通安全或环境污染事故时，应报告船名、船位、事故概况、船上人员情况及救助需求。发现影响航行安全的异常情况时，应报告异常情况及救助需求，系统应优先人工接管。",
    },
    {
        "title": "引航报告",
        "category": "VTS报告规则",
        "source": "船舶报告与引航业务材料",
        "content": "引航登轮、引航活动结束时应向交管中心报告，报告方式为VHF频道，内容包括船名、引航员或编号、引航活动状态等。",
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
                    existing_titles = {str(row.get("title") or "") for row in rows}
                    for index, entry in enumerate(DEFAULT_ENTRIES, start=1):
                        if entry["title"] not in existing_titles:
                            rows.append({"id": f"kb_seed_{index}", **entry})
                    self._entries = rows
                    self._save()
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
