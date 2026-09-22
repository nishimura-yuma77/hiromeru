"""Browser APIの最小Accept negotiation。"""


def accepts_event_stream(value: str | None) -> bool:
    """JSONとSSEの品質値を比較し、明示的に優先されたSSEだけを選ぶ。"""
    if not value:
        return False
    ranges: list[tuple[str, float, int]] = []
    for position, raw in enumerate(value.split(",")):
        parts = [part.strip() for part in raw.split(";")]
        media_type = parts[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            name, separator, parameter_value = parameter.partition("=")
            if name.strip().lower() != "q" or not separator:
                continue
            try:
                quality = float(parameter_value.strip())
            except ValueError:
                quality = 0.0
            if not 0 <= quality <= 1:
                quality = 0.0
        ranges.append((media_type, quality, position))

    def preference(media_type: str) -> tuple[float, int, int]:
        target_type = media_type.split("/", 1)[0]
        matches: list[tuple[int, float, int]] = []
        for candidate, quality, position in ranges:
            specificity = (
                2
                if candidate == media_type
                else 1
                if candidate == f"{target_type}/*"
                else 0
                if candidate == "*/*"
                else -1
            )
            if specificity >= 0:
                matches.append((specificity, quality, position))
        if not matches:
            return (0.0, -1, len(ranges))
        specificity = max(item[0] for item in matches)
        selected = min((item for item in matches if item[0] == specificity), key=lambda x: x[2])
        return (selected[1], specificity, selected[2])

    stream = preference("text/event-stream")
    json = preference("application/json")
    if stream[0] <= 0:
        return False
    if stream[0] != json[0]:
        return stream[0] > json[0]
    if stream[1] != json[1]:
        return stream[1] > json[1]
    return stream[2] < json[2]
