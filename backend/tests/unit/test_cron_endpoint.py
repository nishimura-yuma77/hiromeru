import json
from pathlib import Path

from api.routers.cron import ClaimBudget


def test_Claim_Budgetは240秒未満だけ新しいClaimを許可する() -> None:
    current = [239.999]
    budget = ClaimBudget(240.0, lambda: current[0])

    assert budget.available() is True
    current[0] = 240.0
    assert budget.available() is False
    current[0] = 241.0
    assert budget.available() is False


def test_VercelはProductionで日次Cronを実行しmaxDurationを維持する() -> None:
    config = json.loads(Path("../vercel.json").read_text())

    assert config["crons"] == [{"path": "/api/cron/post-metrics", "schedule": "0 0 * * *"}]
    assert config["services"]["backend"]["functions"]["main.py"]["maxDuration"] == 300
    assert config["rewrites"][0] == {
        "source": "/api/(.*)",
        "destination": {"service": "backend"},
    }
