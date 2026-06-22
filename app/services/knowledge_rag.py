from __future__ import annotations

import os
from typing import Dict, List, Optional

from app.services.knowledge_repository import KnowledgeRepository


class KnowledgeRAGService:
    """LangChain-style RAG over the local knowledge index with LLM answer synthesis."""

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository
        self.model = os.getenv("VHF_KNOWLEDGE_MODEL", os.getenv("VHF_DECISION_MODEL", "qwen-max"))
        self.api_key_env = os.getenv(
            "VHF_KNOWLEDGE_API_KEY_ENV",
            os.getenv("VHF_DECISION_API_KEY_ENV", "DASHSCOPE_API_KEY"),
        )
        self.base_url = os.getenv(
            "VHF_KNOWLEDGE_BASE_URL",
            os.getenv("VHF_DECISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        self.top_k = int(os.getenv("VHF_KNOWLEDGE_TOP_K", "4"))

    def retrieve(self, query: str) -> List[Dict[str, str]]:
        query = (query or "").strip()
        if not query:
            return self.repository.list_entries()[: self.top_k]
        try:
            from langchain_core.documents import Document
            from langchain_community.retrievers import BM25Retriever

            docs = [
                Document(
                    page_content=f"{entry.get('title', '')}\n{entry.get('content', '')}",
                    metadata=entry,
                )
                for entry in self.repository.list_entries()
            ]
            if not docs:
                return []
            retriever = BM25Retriever.from_documents(docs, k=self.top_k)
            hits = retriever.invoke(query)
            return [dict(doc.metadata) for doc in hits if isinstance(doc.metadata, dict)]
        except Exception:
            return self.repository.search(query)[: self.top_k]

    def ask(self, query: str) -> Dict[str, object]:
        query = (query or "").strip()
        if not query:
            raise ValueError("问题不能为空")
        hits = self.retrieve(query)
        if not hits:
            return {
                "question": query,
                "answer": "知识库中暂无相关内容，请先导入资料或补充规则文档。",
                "sources": [],
                "mode": "empty",
            }
        context = "\n\n".join(
            f"[{index + 1}] {item.get('title', '资料')}（{item.get('category', '规则')}）\n{item.get('content', '')}"
            for index, item in enumerate(hits)
        )
        answer = self._call_llm(query, context)
        return {
            "question": query,
            "answer": answer,
            "sources": hits,
            "mode": "langchain_rag",
        }

    def _call_llm(self, question: str, context: str) -> str:
        api_key = os.getenv(self.api_key_env, "")
        if not api_key:
            return self._fallback_answer(question, context)
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_openai import ChatOpenAI

            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "你是海事VHF交管知识助手。只能依据提供的知识片段回答，"
                        "如果资料不足要明确说明，不要编造法规条文。回答简洁、可直接用于值班演示。",
                    ),
                    ("human", "问题：{question}\n\n知识片段：\n{context}"),
                ]
            )
            llm = ChatOpenAI(
                model=self.model,
                api_key=api_key,
                base_url=self.base_url,
                temperature=0.2,
                timeout=int(os.getenv("VHF_KNOWLEDGE_TIMEOUT_S", "20")),
            )
            chain = prompt | llm
            response = chain.invoke({"question": question, "context": context})
            content = getattr(response, "content", None) or str(response)
            return str(content).strip() or self._fallback_answer(question, context)
        except Exception:
            return self._fallback_answer(question, context)

    @staticmethod
    def _fallback_answer(question: str, context: str) -> str:
        first = context.split("\n\n", 1)[0].strip()
        return f"基于知识库检索结果，针对“{question}”可参考：{first[:320]}"
