"""Context圧縮の差し替え境界。実LLM基盤には依存しない。"""

from typing import Protocol

from agent_runtime.runner import AgentContextEntry


class ContextCompactor(Protocol):
    """古い会話ContextからCheckpoint要約を生成する。"""

    async def compact(self, entries: tuple[AgentContextEntry, ...]) -> str:
        """安全に再構築済みの要素だけを要約する。"""
        ...


class StubContextCompactor:
    """Tool/LLM基盤が入るまで使う、決定論的な最小実装。"""

    async def compact(self, entries: tuple[AgentContextEntry, ...]) -> str:
        """詳細要約を行わず、件数だけの安全な短縮表現を返す。"""
        return (
            "Stub runtime compacted earlier conversation history. "
            f"Source context entries: {len(entries)}."
        )
