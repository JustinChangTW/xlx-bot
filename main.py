from xlxbot.application import BotApplication
from xlxbot.config import AppConfig
from xlxbot.logging_setup import setup_logging


def main():
    # 先把環境設定與 logger 建好，後續所有模組都共用這份設定。
    config = AppConfig.from_env()
    logger = setup_logging(
        config.log_file,
        config.log_level,
        config.log_max_bytes,
        config.log_backup_count
    )
    # BotApplication 會負責組合 Flask、LINE webhook 與 AI provider。
    bot_app = BotApplication(logger)
    bot_app.run()


if __name__ == '__main__':
    main()
