"""構造化ログ（structlog）の設定（BE_STD 9章）。

本文（Request Body、LLMの入出力）とCookie・トークンはログへ出さない。
エラーの内容は、マスクしてから出す。
"""

import logging
import sys

import structlog

from core.masking import mask_text


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Structlog と標準loggingを設定する。"""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """名前付きのロガーを返す。"""
    return structlog.get_logger(name)


def safe_error_text(error: BaseException, limit: int = 300) -> str:
    """例外の内容をマスクして短くする。SQLの引数などに機密が含まれ得るため、直接出さない。"""
    return mask_text(f"{type(error).__name__}: {error}")[:limit]
