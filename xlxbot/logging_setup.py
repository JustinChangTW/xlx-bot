import logging
from logging.handlers import RotatingFileHandler


def setup_logging(log_file, log_level, log_max_bytes, log_backup_count):
    # 同時輸出到終端與檔案，方便本機看 log 與長期追蹤問題。
    log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    # 重新設定 root logger，避免重複加 handler 導致同一筆 log 印很多次。
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    return logging.getLogger(__name__)
