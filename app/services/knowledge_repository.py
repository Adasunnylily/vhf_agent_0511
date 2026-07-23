from __future__ import annotations

import json
import re
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

    def rag_context(self, query: str, top_k: int = 5) -> Dict[str, object]:
        """Lightweight LangChain-style retrieval chain without adding server dependencies."""
        chunks = self._rank_chunks(query, top_k=max(1, top_k))
        context = "\n\n".join(
            f"[{index + 1}] {chunk['title']}｜{chunk['category']}｜{chunk['source']}\n{chunk['text']}"
            for index, chunk in enumerate(chunks)
        )
        answer = self._extractive_answer(query, chunks)
        return {
            "query": query,
            "answer": answer,
            "context": context,
            "items": chunks,
            "graph": self.graph(query),
        }

    def graph(self, query: str = "", limit: int = 30) -> Dict[str, object]:
        triples = self._extract_triples()
        if query.strip():
            tokens = self._tokens(query)
            triples = [
                item
                for item in triples
                if any(token in f"{item['source']} {item['relation']} {item['target']}" for token in tokens)
            ] or triples
        triples = triples[: max(1, limit)]
        node_names = []
        for item in triples:
            node_names.extend([item["source"], item["target"]])
        nodes = [{"id": name, "label": name} for name in dict.fromkeys(node_names)]
        return {"nodes": nodes, "edges": triples}

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

    def add_entry(
        self,
        title: str,
        content: str,
        category: str = "人工维护",
        source: str = "manual",
    ) -> Dict[str, str]:
        entry = {
            "id": f"kb_{uuid.uuid4().hex[:12]}",
            "title": title.strip() or "未命名知识",
            "category": category.strip() or "人工维护",
            "source": source.strip() or "manual",
            "content": content.strip(),
            "file_path": "",
        }
        self._entries.append(entry)
        self._save()
        return entry

    def delete_entry(self, entry_id: str) -> bool:
        before = len(self._entries)
        removed = [entry for entry in self._entries if str(entry.get("id") or "") == entry_id]
        self._entries = [entry for entry in self._entries if str(entry.get("id") or "") != entry_id]
        if len(self._entries) == before:
            return False
        for entry in removed:
            file_path = str(entry.get("file_path") or "")
            if file_path:
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
        self._save()
        return True

    @staticmethod
    def _tokens(text: str) -> List[str]:
        raw = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]{2,}", text.lower())
        stop = {"当前", "这个", "什么", "如何", "需要", "进行", "船舶", "交管"}
        domain_terms = [
            "离泊", "起锚", "靠泊", "靠妥", "抛锚", "申请", "处置", "高危", "险情",
            "事故", "异常", "人工", "复核", "自动回复", "报告", "引航", "遇险", "火灾",
            "碰撞", "进水", "失控", "落水", "点验", "广播", "守听",
        ]
        tokens = [token for token in raw if token not in stop]
        for term in domain_terms:
            if term in text:
                tokens.append(term)
        return list(dict.fromkeys(tokens))

    def _chunks(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for entry in self._entries:
            content = str(entry.get("content") or "")
            parts = [part.strip() for part in re.split(r"(?<=[。！？；;\n])", content) if part.strip()]
            if not parts:
                parts = [content[:600]]
            buffer = ""
            chunk_index = 0
            for part in parts:
                if len(buffer) + len(part) > 520 and buffer:
                    rows.append(self._chunk_entry(entry, buffer, chunk_index))
                    chunk_index += 1
                    buffer = part
                else:
                    buffer = f"{buffer}{part}"
            if buffer:
                rows.append(self._chunk_entry(entry, buffer, chunk_index))
        return rows

    @staticmethod
    def _chunk_entry(entry: Dict[str, str], text: str, chunk_index: int) -> Dict[str, str]:
        return {
            "id": f"{entry.get('id', 'kb')}_chunk_{chunk_index}",
            "doc_id": str(entry.get("id") or ""),
            "title": str(entry.get("title") or "未命名资料"),
            "category": str(entry.get("category") or "法规资料"),
            "source": str(entry.get("source") or ""),
            "text": text.strip(),
        }

    def _rank_chunks(self, query: str, top_k: int = 5) -> List[Dict[str, str]]:
        tokens = self._tokens(query)
        if not tokens:
            return self._chunks()[:top_k]
        scored = []
        for chunk in self._chunks():
            haystack = f"{chunk['title']} {chunk['category']} {chunk['source']} {chunk['text']}".lower()
            score = sum(haystack.count(token) for token in tokens)
            if query.strip().lower() in haystack:
                score += 4
            if score:
                scored.append((score, chunk))
        return [chunk for _, chunk in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]]

    @staticmethod
    def _extractive_answer(query: str, chunks: List[Dict[str, str]]) -> str:
        if not chunks:
            return "未检索到直接相关规则，请补充法规资料或换关键词检索。"
        lines = [f"基于知识库检索，和“{query or '当前问题'}”最相关的依据如下："]
        for index, chunk in enumerate(chunks[:3], start=1):
            lines.append(f"{index}. {chunk['title']}：{chunk['text'][:180]}")
        return "\n".join(lines)

    def _extract_triples(self) -> List[Dict[str, str]]:
        triples: List[Dict[str, str]] = []
        patterns = [
            (r"(高危|险情|事故|异常情况|离泊|起锚|靠妥|抛锚|引航|过桥|自动回复)(?:[^。；\n]{0,18})(应|必须|优先|需要)([^。；\n]{2,32})", "处置要求"),
            (r"(船舶|危险品船舶|拖带船队|客船|外国籍船舶)(?:[^。；\n]{0,18})(适用|包括|报告)([^。；\n]{2,32})", "适用规则"),
            (r"(VHF|CH10|CH16|交管中心|报告线)(?:[^。；\n]{0,18})(报告|通信|守听)([^。；\n]{0,32})", "通信规则"),
        ]
        for entry in self._entries:
            content = str(entry.get("content") or "")
            for pattern, relation in patterns:
                for match in re.finditer(pattern, content):
                    source = match.group(1).strip()
                    target = f"{match.group(2)}{match.group(3)}".strip()
                    triples.append(
                        {
                            "source": source,
                            "relation": relation,
                            "target": target,
                            "doc_id": str(entry.get("id") or ""),
                            "title": str(entry.get("title") or ""),
                        }
                    )
        if triples:
            return triples
        return [
            {"source": entry["title"], "relation": "属于", "target": entry["category"], "doc_id": entry["id"], "title": entry["title"]}
            for entry in self._entries
        ]

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
