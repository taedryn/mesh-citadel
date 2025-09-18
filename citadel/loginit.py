import logging


def initialize_logging(config):
    log_path = config.logging["log_file_path"]
    log_level = config.logging.get("log_level", "INFO").upper()

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Avoid duplicate handlers
    if not logger.handlers:
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # File handler
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        logger.info("Logging initialized")
