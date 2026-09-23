import pytest

from api.content_negotiation import accepts_event_stream


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        (None, False),
        ("*/*", False),
        ("text/event-stream", True),
        ("text/event-stream;q=0", False),
        ("application/json, text/event-stream;q=0.9", False),
        ("application/json;q=0.5, text/event-stream;q=0.9", True),
        ("text/event-stream, application/json", True),
        ("text/event-stream;q=0, */*;q=1", False),
        ("text/*;q=0.8, application/json;q=0.7", True),
        ("text/event-stream;q=invalid", False),
    ],
)
def test_Acceptのmedia_typeと品質値でSSEを選択する(
    accept: str | None, expected: bool
) -> None:
    assert accepts_event_stream(accept) is expected
