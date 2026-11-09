import logging
import sys


def setup_logging(level: int = logging.DEBUG) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
    ))
    logging.getLogger().setLevel(level)
    logging.getLogger().addHandler(handler)
    # websockets writes the streaming request line at DEBUG, including the
    # access token in the query string. Keep our own DEBUG logs, but never
    # let that URL reach the log.
    logging.getLogger("websockets").setLevel(logging.INFO)
