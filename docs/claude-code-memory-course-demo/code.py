#!/usr/bin/env python3
"""A teachable, file-based memory system for a small coding agent.

The demo extends the basic "index + topic files + recall" idea with:

1. source_session / source_message traceability
2. recall explanations
3. session memory for compact-time continuity
4. conservative extraction and Dream consolidation
5. an offline --self-test that needs no API key

Run:
    pip install anthropic python-dotenv
    python code.py --self-test
    python code.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

try:
    from anthropic import Anthropic
except ImportError:  # --self-test works without third-party packages
    Anthropic = None  # type: ignore[assignment,misc]


MEMORY_TYPES = {"user", "feedback", "project", "reference"}
MAX_RECALLED = 5
MAX_MEMORY_FILES = 200
MAX_INDEX_LINES = 200
MAX_FILE_CHARS = 4096
CONSOLIDATE_THRESHOLD = 10
SESSION_UPDATE_EVERY = 4


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value.strip().lower())
    return value.strip("-")[:80] or f"memory-{int(time.time())}"


def extract_json(text: str, expected: type) -> Any:
    """Extract the first JSON object/array with a deliberately small parser."""
    opener, closer = ("[", "]") if expected is list else ("{", "}")
    start = text.find(opener)
    end = text.rfind(closer)
    if start < 0 or end < start:
        raise ValueError("model response did not contain JSON")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, expected):
        raise ValueError(f"expected {expected.__name__}")
    return value


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        elif getattr(block, "type", None) == "text":
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(part for part in parts if part)


def search_tokens(text: str) -> set[str]:
    """Tokenize English words and Chinese bigrams for the offline fallback."""
    lowered = text.lower()
    tokens = {word for word in re.findall(r"[a-z0-9_-]+", lowered) if len(word) > 1}
    for chunk in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(chunk) == 1:
            tokens.add(chunk)
        else:
            tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return tokens


@dataclass
class Message:
    id: str
    role: str
    content: str
    created_at: str


@dataclass
class Memory:
    filename: str
    name: str
    description: str
    type: str
    body: str
    source_session: str
    source_message: str
    created_at: str
    updated_at: str


@dataclass
class Recall:
    filename: str
    reason: str


class LLM:
    """Thin wrapper so the memory code is not coupled to the CLI loop."""

    def __init__(self) -> None:
        if Anthropic is None:
            raise RuntimeError("Install dependencies: pip install anthropic python-dotenv")
        self.model = os.getenv("MODEL_ID", "").strip()
        if not self.model:
            raise RuntimeError("Set MODEL_ID to a model available on your Anthropic endpoint")
        kwargs: dict[str, Any] = {}
        if os.getenv("ANTHROPIC_BASE_URL"):
            kwargs["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        self.client = Anthropic(**kwargs)

    def ask(self, prompt: str, *, system: str = "", max_tokens: int = 1200) -> str:
        response = self.client.messages.create(
            model=self.model,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return text_from_content(response.content).strip()


class MemoryStore:
    """Markdown topic files, a short MEMORY.md index, and source traces."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = root / "MEMORY.md"

    @staticmethod
    def _parse(text: str, filename: str) -> Memory:
        meta: dict[str, str] = {}
        body = text
        if text.startswith("---\n"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        meta[key.strip()] = value.strip().strip('"').strip("'")
                body = parts[2].strip()
        return Memory(
            filename=filename,
            name=meta.get("name", Path(filename).stem),
            description=meta.get("description", ""),
            type=meta.get("type", "project"),
            body=body,
            source_session=meta.get("source_session", "unknown"),
            source_message=meta.get("source_message", "unknown"),
            created_at=meta.get("created_at", "unknown"),
            updated_at=meta.get("updated_at", "unknown"),
        )

    def list(self) -> list[Memory]:
        paths = sorted(
            (p for p in self.root.glob("*.md") if p.name != "MEMORY.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:MAX_MEMORY_FILES]
        return [self._parse(path.read_text(encoding="utf-8"), path.name) for path in paths]

    def read(self, filename: str) -> Memory | None:
        safe_name = Path(filename).name
        path = self.root / safe_name
        if not path.is_file() or safe_name == "MEMORY.md":
            return None
        return self._parse(path.read_text(encoding="utf-8"), safe_name)

    def write(
        self,
        *,
        name: str,
        description: str,
        mem_type: str,
        body: str,
        source_session: str,
        source_message: str,
    ) -> Memory:
        if mem_type not in MEMORY_TYPES:
            raise ValueError(f"invalid memory type: {mem_type}")
        filename = f"{slugify(name)}.md"
        path = self.root / filename
        existing = self.read(filename)
        created_at = existing.created_at if existing else now_iso()
        memory = Memory(
            filename=filename,
            name=name,
            description=" ".join(description.split())[:240],
            type=mem_type,
            body=body.strip(),
            source_session=source_session,
            source_message=source_message,
            created_at=created_at,
            updated_at=now_iso(),
        )
        path.write_text(
            "---\n"
            f"name: {memory.name}\n"
            f"description: {memory.description}\n"
            f"type: {memory.type}\n"
            f"source_session: {memory.source_session}\n"
            f"source_message: {memory.source_message}\n"
            f"created_at: {memory.created_at}\n"
            f"updated_at: {memory.updated_at}\n"
            "---\n\n"
            f"{memory.body}\n",
            encoding="utf-8",
        )
        self.rebuild_index()
        return memory

    def delete(self, filename: str) -> bool:
        path = self.root / Path(filename).name
        if path.is_file() and path.name != "MEMORY.md":
            path.unlink()
            self.rebuild_index()
            return True
        return False

    def rebuild_index(self) -> None:
        lines = [
            f"- [{m.name}]({m.filename}) — {m.description}"
            for m in sorted(self.list(), key=lambda item: item.name.lower())
        ][:MAX_INDEX_LINES]
        self.index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def index(self) -> str:
        if not self.index_path.exists():
            return ""
        return "\n".join(self.index_path.read_text(encoding="utf-8").splitlines()[:MAX_INDEX_LINES])


class SessionJournal:
    """Current-session continuity notes. This is not durable Auto Memory."""

    def __init__(self, root: Path, session_id: str) -> None:
        self.path = root / session_id / "session-memory.md"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                "# Current State\n\n# User Constraints\n\n# Key Results\n\n# Worklog\n",
                encoding="utf-8",
            )

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def update(self, llm: LLM, messages: list[Message]) -> None:
        recent = "\n".join(f"{m.role}: {m.content}" for m in messages[-8:])
        prompt = f"""Update the session note from the recent conversation.
Return Markdown with exactly these headings and no others:
# Current State
# User Constraints
# Key Results
# Worklog
Keep concrete paths, errors, commands, and immediate next steps. This note is only
for continuity inside the current session; do not create long-term user memories.

Current note:
{self.read()}

Recent conversation:
{recent}
"""
        self.path.write_text(llm.ask(prompt, max_tokens=900).strip() + "\n", encoding="utf-8")


class TranscriptStore:
    """Append-only JSONL transcripts that make source ids resolvable."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, session_id: str, message: Message) -> None:
        path = self.root / f"{session_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")

    def find(self, session_id: str, message_id: str) -> Message | None:
        path = self.root / f"{Path(session_id).name}.jsonl"
        if not path.is_file():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("id") == message_id:
                return Message(**item)
        return None


class MemoryEngine:
    def __init__(self, store: MemoryStore, llm: LLM | None) -> None:
        self.store = store
        self.llm = llm

    def recall(self, query: str) -> list[Recall]:
        memories = self.store.list()
        if not memories:
            return []
        manifest = "\n".join(
            f"- {m.filename} | {m.name} | {m.description}" for m in memories
        )
        if self.llm is not None:
            prompt = f"""Select up to {MAX_RECALLED} memories that are clearly useful.
Be conservative: when unsure, do not select. Explain each selection briefly.
Return only JSON:
{{"selected": [{{"filename": "x.md", "reason": "..."}}]}}

Query: {query}

Memory manifest:
{manifest}
"""
            try:
                result = extract_json(self.llm.ask(prompt, max_tokens=500), dict)
                valid = {m.filename for m in memories}
                recalls = [
                    Recall(str(item["filename"]), str(item.get("reason", "语义相关")))
                    for item in result.get("selected", [])
                    if isinstance(item, dict) and item.get("filename") in valid
                ]
                return recalls[:MAX_RECALLED]
            except Exception as exc:
                print(f"[recall selector fallback: {exc}]", file=sys.stderr)

        # Offline and error fallback: simple token overlap, still with an explanation.
        query_words = search_tokens(query)
        scored: list[tuple[int, Memory]] = []
        for memory in memories:
            haystack_words = search_tokens(f"{memory.name} {memory.description}")
            score = len(query_words & haystack_words)
            if score:
                scored.append((score, memory))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            Recall(memory.filename, f"关键词重合 {score} 项")
            for score, memory in scored[:MAX_RECALLED]
        ]

    def render_recalled(self, recalls: list[Recall]) -> str:
        sections: list[str] = []
        for recall in recalls:
            memory = self.store.read(recall.filename)
            if not memory:
                continue
            sections.append(
                f"## {memory.name}\n"
                f"Recall reason: {recall.reason}\n"
                f"Source: session={memory.source_session}, message={memory.source_message}\n"
                f"Freshness: updated_at={memory.updated_at}\n\n"
                f"{memory.body[:MAX_FILE_CHARS]}"
            )
        return "\n\n".join(sections)

    def extract(self, messages: list[Message], session_id: str) -> list[Memory]:
        if self.llm is None or not messages:
            return []
        recent = messages[-10:]
        dialogue = "\n".join(f"[{m.id}] {m.role}: {m.content}" for m in recent)
        existing = "\n".join(
            f"- {m.filename}: {m.description}" for m in self.store.list()
        ) or "(none)"
        prompt = f"""Extract only durable, non-obvious information useful in future sessions.
Allowed types: user, feedback, project, reference.
Do NOT save current task progress, code facts that can be re-read, git history, or
anything already covered by existing memories. Preserve the source message id.
Return only a JSON array. Each item must contain:
name, type, description, body, source_message.
If nothing qualifies, return [].

Existing memories:
{existing}

Recent dialogue:
{dialogue}
"""
        try:
            items = extract_json(self.llm.ask(prompt, max_tokens=1200), list)
        except Exception as exc:
            print(f"[memory extraction skipped: {exc}]", file=sys.stderr)
            return []

        valid_message_ids = {message.id for message in recent}
        written: list[Memory] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mem_type = str(item.get("type", ""))
            source_message = str(item.get("source_message", ""))
            if mem_type not in MEMORY_TYPES or source_message not in valid_message_ids:
                continue
            if not all(str(item.get(key, "")).strip() for key in ("name", "description", "body")):
                continue
            written.append(
                self.store.write(
                    name=str(item["name"]),
                    description=str(item["description"]),
                    mem_type=mem_type,
                    body=str(item["body"]),
                    source_session=session_id,
                    source_message=source_message,
                )
            )
        return written

    def dream(self) -> str:
        if self.llm is None:
            return "Dream requires an LLM."
        memories = self.store.list()
        if len(memories) < CONSOLIDATE_THRESHOLD:
            return f"Dream skipped: {len(memories)} < {CONSOLIDATE_THRESHOLD} memories."
        payload = json.dumps([asdict(memory) for memory in memories], ensure_ascii=False)
        prompt = f"""Consolidate these memory records.
- Merge near-duplicates by topic.
- Preserve source_session and source_message from the strongest source.
- Remove stale or contradicted records only when the supplied records justify it.
- Keep user preferences and project-wide feedback precise.
Return only a JSON array with fields:
name, type, description, body, source_session, source_message, created_at.

Memories:
{payload[:24000]}
"""
        try:
            items = extract_json(self.llm.ask(prompt, max_tokens=3000), list)
        except Exception as exc:
            return f"Dream failed safely; original files kept: {exc}"

        validated = [
            item
            for item in items
            if isinstance(item, dict)
            and item.get("type") in MEMORY_TYPES
            and all(str(item.get(k, "")).strip() for k in ("name", "description", "body"))
        ]
        if not validated:
            return "Dream returned no valid memories; original files kept."

        # Transaction-like replacement: build a sibling directory, then swap.
        temp_root = self.store.root.with_name(self.store.root.name + ".dream-new")
        backup_root = self.store.root.with_name(self.store.root.name + ".dream-backup")
        shutil.rmtree(temp_root, ignore_errors=True)
        shutil.rmtree(backup_root, ignore_errors=True)
        new_store = MemoryStore(temp_root)
        for item in validated:
            new_store.write(
                name=str(item["name"]),
                description=str(item["description"]),
                mem_type=str(item["type"]),
                body=str(item["body"]),
                source_session=str(item.get("source_session", "dream")),
                source_message=str(item.get("source_message", "dream")),
            )
        self.store.root.rename(backup_root)
        temp_root.rename(self.store.root)
        shutil.rmtree(backup_root, ignore_errors=True)
        return f"Dream consolidated {len(memories)} → {len(validated)} memories."


class CodingAgent:
    def __init__(self, workspace: Path, llm: LLM) -> None:
        self.workspace = workspace.resolve()
        self.llm = llm
        self.session_id = uuid.uuid4().hex[:12]
        self.store = MemoryStore(self.workspace / ".memory")
        self.engine = MemoryEngine(self.store, llm)
        self.journal = SessionJournal(self.workspace / ".sessions", self.session_id)
        self.transcripts = TranscriptStore(self.workspace / ".transcripts")
        self.messages: list[Message] = []
        self.turns = 0

    def add(self, role: str, content: str) -> Message:
        message = Message(uuid.uuid4().hex[:10], role, content, now_iso())
        self.messages.append(message)
        self.transcripts.append(self.session_id, message)
        return message

    def answer(self, query: str) -> str:
        user_message = self.add("user", query)
        recalls = self.engine.recall(query)
        if recalls:
            print("\n[Recall]")
            for recall in recalls:
                print(f"  {recall.filename}: {recall.reason}")
        recalled = self.engine.render_recalled(recalls) or "(none)"
        prompt = f"""You are a small coding-agent teaching demo running at {self.workspace}.
Answer the user's request. Recalled memories are fallible historical context:
verify current files before relying on claims about code, paths, functions, or flags.

Memory index:
{self.store.index() or '(empty)'}

Relevant memories with traceability:
{recalled}

Current session note:
{self.journal.read()}

User query:
{query}
"""
        answer = self.llm.ask(prompt, max_tokens=1800)
        self.add("assistant", answer)
        written = self.engine.extract(self.messages, self.session_id)
        if written:
            print(f"[Extracted {len(written)} memories: {', '.join(m.filename for m in written)}]")
        self.turns += 1
        if self.turns % SESSION_UPDATE_EVERY == 0:
            self.journal.update(self.llm, self.messages)
            print(f"[Session memory updated: {self.journal.path}]")
        return answer


def run_cli(workspace: Path) -> None:
    agent = CodingAgent(workspace, LLM())
    print("Memory course demo")
    print("Commands: /memory, /trace <file>, /session, /dream, /new, /exit\n")
    while True:
        try:
            query = input("memory-demo >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query in {"/exit", "q", "exit"}:
            break
        if query == "/memory":
            print(agent.store.index() or "(empty)")
            continue
        if query.startswith("/trace "):
            memory = agent.store.read(query.split(maxsplit=1)[1])
            if not memory:
                print("not found")
                continue
            source = agent.transcripts.find(memory.source_session, memory.source_message)
            print(json.dumps({"memory": asdict(memory), "source": asdict(source) if source else None}, ensure_ascii=False, indent=2))
            continue
        if query == "/session":
            print(agent.journal.read())
            continue
        if query == "/dream":
            print(agent.engine.dream())
            continue
        if query == "/new":
            agent = CodingAgent(workspace, agent.llm)
            print(f"new session: {agent.session_id}")
            continue
        print("\n" + agent.answer(query) + "\n")


def self_test() -> None:
    """Deterministic smoke test for storage, trace, recall, deletion and isolation."""
    with tempfile.TemporaryDirectory(prefix="memory-course-") as temp:
        root = Path(temp)
        store = MemoryStore(root / ".memory")
        memory = store.write(
            name="real-database-tests",
            description="集成测试必须连接真实测试数据库，不使用 mock",
            mem_type="feedback",
            body="规则：集成测试使用隔离的真实数据库。\n\n**Why:** mock 曾掩盖迁移错误。",
            source_session="session-demo",
            source_message="message-001",
        )
        assert store.index().startswith("- [real-database-tests]")
        loaded = store.read(memory.filename)
        assert loaded and loaded.source_message == "message-001"

        engine = MemoryEngine(store, llm=None)
        recalls = engine.recall("真实数据库测试")
        assert recalls and recalls[0].filename == memory.filename
        rendered = engine.render_recalled(recalls)
        assert "session-demo" in rendered and "message-001" in rendered

        journal = SessionJournal(root / ".sessions", "session-demo")
        assert "# Current State" in journal.read()
        transcripts = TranscriptStore(root / ".transcripts")
        source = Message("message-001", "user", "测试不要 mock 数据库", now_iso())
        transcripts.append("session-demo", source)
        assert transcripts.find("session-demo", "message-001") == source
        assert store.delete(memory.filename)
        assert store.list() == []
        print("self-test passed: store → index → recall → trace → session → delete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run without API access")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run_cli(args.workspace)


if __name__ == "__main__":
    main()
