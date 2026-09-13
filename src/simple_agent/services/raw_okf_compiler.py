from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simple_agent.llm import create_llm
from simple_agent.services.okf_store import PersistentOKFStore


PLANNER_PROMPT = """You are an OKF 0.2 knowledge compiler.
Analyze the raw source and propose a conservative ingestion plan for the existing OKF bundle.
Return ONLY valid JSON with this shape:
{
  "summary": "short summary",
  "institution": "name or null",
  "product": "name or null",
  "domain": "GLOBAL|INSTITUTIONS|PRODUCTS",
  "files": [
    {
      "path": "relative/path.md",
      "title": "title",
      "type": "Knowledge|Policy|Procedure|Reference",
      "content": "complete markdown body without yaml frontmatter",
      "reason": "why this path"
    }
  ],
  "warnings": ["..."],
  "assumptions": ["..."]
}
Rules:
- Never invent facts absent from the raw source.
- Prefer INSTITUTIONS/<slug>/... for institution-specific facts.
- Prefer PRODUCTS/<slug>/... for product-specific facts not tied to one institution.
- Prefer GLOBAL/... only for cross-cutting rules.
- Use lowercase snake_case path segments.
- Create focused concept documents; do not create redundant copies.
- Do not generate index.md; indexes are maintained by the runtime.
- If uncertain, include the uncertainty in warnings and keep the plan conservative.
"""


class RawOKFCompiler:
    def __init__(self, store: PersistentOKFStore | None = None):
        self.store = store or PersistentOKFStore()
        self.raw_root = self.store.root / "raw"
        self.raw_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(value: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.").lower()
        return clean[:80] or "raw"

    def analyze(self, source_name: str, raw_text: str) -> dict[str, Any]:
        if not raw_text or not raw_text.strip():
            raise ValueError("raw_text is required")
        if len(raw_text) > 250_000:
            raise ValueError("RAW source is too large for one compiler run (max 250000 chars)")

        ingestion_id = f"{self._slug(source_name)}-{uuid.uuid4().hex[:8]}"
        root = self.raw_root / ingestion_id
        root.mkdir(parents=True, exist_ok=False)
        (root / "source.txt").write_text(raw_text, encoding="utf-8")

        llm = create_llm()
        response = llm.invoke([
            ("system", PLANNER_PROMPT),
            ("user", f"SOURCE NAME: {source_name}\n\nRAW SOURCE:\n{raw_text}"),
        ])
        text = response.content if isinstance(response.content, str) else str(response.content)
        plan = self._parse_json(text)
        plan = self._normalize_plan(plan)
        payload = {
            "ingestion_id": ingestion_id,
            "source_name": source_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plan": plan,
        }
        (root / "plan.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def create_draft(self, ingestion_id: str) -> dict[str, Any]:
        root = (self.raw_root / self._slug(ingestion_id)).resolve()
        if not root.is_relative_to(self.raw_root.resolve()) or not root.is_dir():
            raise FileNotFoundError(f"RAW ingestion not found: {ingestion_id}")
        payload = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        plan = payload.get("plan") or {}
        files = plan.get("files") or []
        if not isinstance(files, list) or not files:
            raise ValueError("Plan has no files to compile")

        draft = self.store.create_draft(f"raw-{payload.get('source_name') or ingestion_id}", "0.2", True)
        draft_id = str(draft["draft_id"])
        touched: list[str] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            content = self._render_concept(item, payload)
            self.store.write_draft_file(draft_id, path, content)
            touched.append(path)
            self._ensure_indexes(draft_id, path)

        validation = self.store.validate_draft(draft_id)
        return {
            "draft_id": draft_id,
            "ingestion_id": ingestion_id,
            "files_written": touched,
            "validation": validation,
        }

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
            candidate = re.sub(r"\s*```$", "", candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError("Compiler returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("Compiler plan must be a JSON object")
        return data

    def _normalize_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        domain = str(plan.get("domain") or "GLOBAL").upper()
        if domain not in {"GLOBAL", "INSTITUTIONS", "PRODUCTS"}:
            domain = "GLOBAL"
        normalized_files: list[dict[str, Any]] = []
        for raw in plan.get("files") or []:
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("path") or "").replace("\\", "/").strip("/")
            if not path.endswith(".md") or path.endswith("index.md") or ".." in Path(path).parts:
                continue
            if path.split("/", 1)[0].upper() not in {"GLOBAL", "INSTITUTIONS", "PRODUCTS"}:
                path = f"{domain}/{path}"
            normalized_files.append({
                "path": path,
                "title": str(raw.get("title") or Path(path).stem.replace("_", " ").title()),
                "type": str(raw.get("type") or "Knowledge"),
                "content": str(raw.get("content") or "").strip(),
                "reason": str(raw.get("reason") or ""),
            })
        return {
            "summary": str(plan.get("summary") or ""),
            "institution": plan.get("institution"),
            "product": plan.get("product"),
            "domain": domain,
            "files": normalized_files,
            "warnings": [str(x) for x in (plan.get("warnings") or [])],
            "assumptions": [str(x) for x in (plan.get("assumptions") or [])],
        }

    @staticmethod
    def _render_concept(item: dict[str, Any], payload: dict[str, Any]) -> str:
        title = str(item.get("title") or "Knowledge")
        concept_type = str(item.get("type") or "Knowledge")
        body = str(item.get("content") or "").strip()
        source_name = str(payload.get("source_name") or "RAW source")
        return (
            "---\n"
            f"type: {json.dumps(concept_type, ensure_ascii=False)}\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            "status: draft\n"
            'okf_version: "0.2"\n'
            f"source: {json.dumps(source_name, ensure_ascii=False)}\n"
            "---\n\n"
            f"# {title}\n\n{body}\n"
        )

    def _ensure_indexes(self, draft_id: str, concept_path: str) -> None:
        parts = Path(concept_path).parts
        for depth in range(1, len(parts)):
            directory = Path(*parts[:depth])
            index_path = (directory / "index.md").as_posix()
            child = parts[depth]
            is_file = depth == len(parts) - 1
            label = Path(child).stem.replace("_", " ").title() if is_file else child.replace("_", " ").title()
            target = child if is_file else f"{child}/"
            files = self.store.draft_files(draft_id)
            existing = files.get(index_path, f"# {directory.as_posix()}\n\n## Conteúdo\n")
            link = f"* [{label}]({target})"
            if link not in existing:
                if not existing.endswith("\n"):
                    existing += "\n"
                existing += f"{link}\n"
                self.store.write_draft_file(draft_id, index_path, existing)
