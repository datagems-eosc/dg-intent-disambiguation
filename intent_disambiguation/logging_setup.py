import logging
import sys

import structlog
from structlog.types import EventDict, Processor


def _drop_color_message_key(_, __, event_dict: EventDict) -> EventDict:
    """Uvicorn repeats the message in `color_message`; drop the duplicate."""
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(json_logs: bool, log_level: str) -> None:
    """Route structlog and stdlib (uvicorn, httpx) logs through one formatter.

    Request-scoped values bound with ``structlog.contextvars`` (the correlation id,
    the calling client) are merged into every line.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        _drop_color_message_key,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if json_logs:
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Uvicorn installs its own handlers before importing the app; send its logs
    # through ours instead. Access logs are written by our middleware.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
    # httpx logs every request at INFO, including the SCAYLE login
    logging.getLogger("httpx").setLevel(logging.WARNING)


logger = structlog.stdlib.get_logger("dg-intent-disambiguation")
