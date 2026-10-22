import asyncio
import io
import sys
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from models import Admin, Company, User
from repositories.database import SessionLocal

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import setup_company

STRONG_PASSWORD = "Strong-Passw0rd!"


def _run(
    email: str, password: str, monkeypatch: pytest.MonkeyPatch, company: str = "スクリプト社"
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{password}\n"))
    setup_company.main(
        ["--company", company, "--name", "責任者", "--email", email, "--password-stdin"]
    )


async def test_初期設定_会社と責任者を登録し管理ユーザーとしてログインできる(
    anonymous: AsyncClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"

    await asyncio.to_thread(_run, f"  {email.upper()} ", STRONG_PASSWORD, monkeypatch)

    assert "登録しました" in capsys.readouterr().out
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        admin = (await session.execute(select(Admin).where(Admin.user_id == user.id))).scalar_one()
    assert user.status == "active" and user.name == "責任者"
    assert admin.is_responsible is True and admin.company_id == user.company_id
    marketer_login = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"Origin": "http://localhost:3000"},
    )
    admin_login = await anonymous.post(
        "/api/v1/admin/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"Origin": "http://localhost:3000"},
    )
    assert marketer_login.status_code == 401
    assert admin_login.status_code == 200


@pytest.mark.parametrize(
    "password",
    ["Short-1a", "alllowercase-123", "NoDigits-Password", "NoSymbol1Password", "Has Space-1Aa"],
)
async def test_初期設定_パスワード条件を満たさないときは登録せず終了する(
    monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    with pytest.raises(SystemExit, match="パスワード"):
        await asyncio.to_thread(_run, f"{uuid.uuid4().hex}@example.com", password, monkeypatch)


async def test_初期設定_メールアドレスが使用済みのとき会社も登録せず終了する(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"{uuid.uuid4().hex}@example.com"
    company = f"重複確認-{uuid.uuid4().hex}"
    await asyncio.to_thread(_run, email, STRONG_PASSWORD, monkeypatch)

    with pytest.raises(SystemExit, match="すでに使われています"):
        await asyncio.to_thread(_run, email.upper(), STRONG_PASSWORD, monkeypatch, company)

    async with SessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(Company).where(Company.name == company)
        )
    assert count == 0
