from domain.evaluation_memory import build_evaluation_memory_content


def test_評価記憶はURLと改行を除いた固定5行Templateになる() -> None:
    content = build_evaluation_memory_content(
        "  Ｗｅｂ採用\n施策  ",
        "詳細は HTTPS://example.com/path?q=1  を確認\nしてください https://example.org",
        1200,
        45,
    )

    assert content == (
        "施策タイトル: Web採用 施策\n"
        "投稿本文: 詳細は を確認 してください\n"
        "初週PV: 1200\n"
        "流入ユーザー: 45\n"
        "流入率: 45/1200"
    )
    assert not content.endswith("\n")


def test_評価記憶はPV0の流入率を決定論的に表現する() -> None:
    content = build_evaluation_memory_content("施策", "投稿", 0, 0)

    assert content.endswith("流入率: 算出不可（初週PVが0）")
