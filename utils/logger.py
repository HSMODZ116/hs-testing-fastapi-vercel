import logging

LOGGER = logging.getLogger("a360")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    handler.setFormatter(fmt)
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
