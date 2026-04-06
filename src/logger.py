import logging
import sys


def setup_logging(level: int = logging.DEBUG) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
    ))
    logging.getLogger().setLevel(level)
    logging.getLogger().addHandler(handler)
