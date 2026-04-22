import datetime
import os
from dataclasses import dataclass


@dataclass
class KnowledgeSection:
    path: str
    content: str


def ensure_memory_dirs(config, logger):
    # 每日記憶會寫進 memory/，啟動或讀寫前先確保目錄存在。
    try:
        os.makedirs(config.memory_dir, exist_ok=True)
        logger.debug('Memory directory ready: %s', config.memory_dir)
    except Exception as e:
        logger.error('Cannot create memory directory %s: %s', config.memory_dir, e)


def get_daily_memory_path(config, days_ago=0):
    date_str = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
    return os.path.join(config.memory_dir, f'{date_str}.md')


def read_text_file(file_path, logger, max_chars=None):
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return None
            if max_chars and len(content) > max_chars:
                # 記憶檔可能很大，超過上限時只保留尾端較新的內容進 prompt。
                logger.debug('Truncating %s to last %s chars for prompt', file_path, max_chars)
                return content[-max_chars:]
            return content
    except Exception as e:
        logger.error('Cannot read file %s: %s', file_path, e)
        return None


def list_markdown_files(directory):
    if not directory or not os.path.isdir(directory):
        return []

    markdown_files = []
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith('.md'):
            continue
        file_path = os.path.join(directory, entry)
        if os.path.isfile(file_path):
            markdown_files.append(file_path)
    return markdown_files


def get_knowledge_files(config, logger):
    # 知識來源包含固定檔、模組化 knowledge/skills/，以及近期記憶。
    potential_files = [
        config.soul_file,
        config.agents_file,
        config.user_file,
        config.long_term_memory_file,
        config.knowledge_file,
        'courses.md',
        'learned_knowledge.txt'
    ]

    potential_files.extend(list_markdown_files('knowledge'))

    skill_files = list_markdown_files('skills')
    if skill_files:
        potential_files.extend(skill_files)
    else:
        potential_files.append('skills.md')

    for days_ago in range(config.daily_memory_lookback_days):
        potential_files.append(get_daily_memory_path(config, days_ago))

    existing_files = [f for f in potential_files if f and os.path.exists(f)]
    logger.debug('Found potential knowledge files: %s', existing_files)
    return existing_files


def is_memory_like_file(config, file_path):
    normalized = file_path.replace('\\', '/')
    return normalized.startswith(config.memory_dir) or '/memory/' in normalized or normalized.endswith('memory.md')


def check_knowledge_file(config, logger):
    ensure_memory_dirs(config, logger)
    kb_files = get_knowledge_files(config, logger)
    if not kb_files:
        logger.error('No knowledge files found. Please check file paths and names in your configuration.')
        return False

    for kb_file in kb_files:
        if os.path.getsize(kb_file) > 0:
            logger.info('Knowledge file check passed. Found content in %s', kb_file)
            return True

    logger.error('All found knowledge files are empty: %s', kb_files)
    return False


def load_knowledge_sections(config, logger):
    ensure_memory_dirs(config, logger)
    sections = []
    kb_files = get_knowledge_files(config, logger)

    for kb_file in kb_files:
        max_chars = 15000 if is_memory_like_file(config, kb_file) else None
        content = read_text_file(kb_file, logger, max_chars=max_chars)
        if content:
            all_content.append(f"--- 來自 {kb_file} ---\n{content}")
            logger.info('Loaded knowledge file: %s (%d chars)', kb_file, len(content))
        elif os.path.exists(kb_file):
            logger.warning('Knowledge file %s is empty', kb_file)

    if not all_content:
        logger.error('No knowledge files with content were loaded!')
        return None

    combined = '\n\n'.join(all_content)
    logger.info('Total knowledge base size: %d chars', len(combined))
    return combined


def refresh_memory_if_needed(config, logger, ask_ollama_func):
    if not config.memory_summarize_enabled:
        return

    daily_path = get_daily_memory_path(config, 0)
    if not os.path.exists(daily_path):
        return

    try:
        file_size = os.path.getsize(daily_path)
        if file_size < config.max_memory_file_chars:
            return

        logger.info(
            'Daily memory size %s exceeds threshold %s, summarizing to %s',
            file_size,
            config.max_memory_file_chars,
            config.long_term_memory_file
        )
        content = read_text_file(daily_path, logger)
        if not content:
            return

        summary_prompt = (
            '你是一個記憶管理系統。請閱讀以下今日日誌，提煉出最重要的資訊，'
            '並生成一個簡短、清楚的長期記憶摘要，適合儲存在 memory.md。'
            '請使用繁體中文，不要加入執行步驟說明。\n\n'
            f'=== 今日日誌 ===\n{content}\n\n'
        )

        # 把過長的每日記錄濃縮到 memory.md，避免後續 prompt 無限制膨脹。
        summary = ask_ollama_func(summary_prompt)
        if summary:
            with open(config.long_term_memory_file, 'a', encoding='utf-8') as f:
                f.write('\n\n--- 自動記憶摘要 {} ---\n{}'.format(datetime.datetime.now().isoformat(), summary.strip()))
            logger.info('Appended memory summary to %s', config.long_term_memory_file)
        else:
            logger.warning('Memory summarization returned no result')
    except Exception as e:
        logger.error('Failed to refresh memory: %s', e)


def append_memory_entry(config, logger, ask_ollama_func, user_id, user_input, ai_response):
    ensure_memory_dirs(config, logger)
    daily_path = get_daily_memory_path(config, 0)
    try:
        # 每次對話都先寫入當日記錄，讓知識與上下文可以逐步累積。
        with open(daily_path, 'a', encoding='utf-8') as f:
            f.write('### {} user_id={}\n'.format(datetime.datetime.now().isoformat(), user_id or 'unknown'))
            f.write('- 用戶：{}\n'.format(user_input.replace('\n', ' ')))
            f.write('- 小龍蝦：{}\n\n'.format(ai_response.replace('\n', ' ')))
        logger.debug('Appended conversation to %s', daily_path)
        refresh_memory_if_needed(config, logger, ask_ollama_func)
    except Exception as e:
        logger.error('Cannot append memory entry: %s', e)
