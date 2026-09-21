import asyncio
import io
import sys
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import create_marketer


def _run(email: str, password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{password}\n"))
    create_marketer.main(
        ["--company", "スクリプト社", "--name", "太郎", "--email", email, "--password-stdin"]
    )


async def test_初期データ投入_作成したマーケターでログインできる(
    anonymous: AsyncClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"

    await asyncio.to_thread(_run, email.upper(), "long-enough-pass", monkeypatch)

    assert "作成しました" in capsys.readouterr().out
    response = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "long-enough-pass"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200


async def test_初期データ投入_パスワードが短いときは作成せず終了する(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit, match="12文字"):
        await asyncio.to_thread(_run, f"{uuid.uuid4().hex}@example.com", "short", monkeypatch)


async def test_初期データ投入_同じメールアドレスが既にあるときは終了する(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    await asyncio.to_thread(_run, email, "long-enough-pass", monkeypatch)

    with pytest.raises(SystemExit, match="既に存在"):
        await asyncio.to_thread(_run, email, "long-enough-pass", monkeypatch)
