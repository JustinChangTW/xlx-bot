import datetime
import json
import os
import re
from collections import Counter


def get_learning_paths(config):
    base = config.memory_dir
    return {
        'events': os.path.join(base, 'learning_events.jsonl'),
        'lessons': os.path.join(base, 'lessons_learned.md'),
        'troubleshooting': os.path.join(base, 'troubleshooting.md'),
        'pending_knowledge': 'learned_knowledge.txt'
    }


def append_learning_event(
    config,
    logger,
    event_type,
    user_id=None,
    user_input=None,
    bot_response=None,
    details=None,
    intent='unknown',
    action='unknown',
    risk='unknown',
    approval='not_required',
    fallback='none',
):
    paths = get_learning_paths(config)
    os.makedirs(config.memory_dir, exist_ok=True)
    event = {
        'ts': datetime.datetime.now().isoformat(),
        'event_type': event_type,
        'user_id': user_id or 'unknown',
        'user_input': (user_input or '')[:500],
        'bot_response': (bot_response or '')[:500],
        'details': details or {},
        'intent': intent,
        'action': action,
        'risk': risk,
        'approval': approval,
        'fallback': fallback,
    }
    try:
        with open(paths['events'], 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.error('Failed to append learning event: %s', e)


def detect_user_correction(user_text):
    text = (user_text or '').strip()
    correction_signals = ['你錯了', '你剛剛', '應該是', '不是', '更正', '修正', '請改成']
    return any(signal in text for signal in correction_signals)


def append_pending_knowledge(config, logger, fact, source='ai_learned_tag', user_id=None):
    paths = get_learning_paths(config)
    line = f"- [PENDING_REVIEW] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} source={source} user_id={user_id or 'unknown'} fact={fact.strip()}\n"
    try:
        with open(paths['pending_knowledge'], 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception as e:
        logger.error('Failed to append pending knowledge: %s', e)


def read_recent_learning_events(config, logger, max_lines=300):
    paths = get_learning_paths(config)
    if not os.path.exists(paths['events']):
        return []

    try:
        with open(paths['events'], 'r', encoding='utf-8') as f:
            lines = f.readlines()[-max_lines:]
    except Exception as e:
        logger.error('Failed to read learning events: %s', e)
        return []

    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def rebuild_lessons_and_troubleshooting(config, logger):
    paths = get_learning_paths(config)
    events = read_recent_learning_events(config, logger)
    if not events:
        return

    event_counts = Counter(event.get('event_type', 'UNKNOWN') for event in events)
    detail_counts = Counter()
    for event in events:
        details = event.get('details') or {}
        reason = details.get('reason') or details.get('error_type') or details.get('category')
        if reason:
            detail_counts[reason] += 1

    top_issue_lines = []
    for reason, count in detail_counts.most_common(5):
        if count >= 2:
            top_issue_lines.append(f'- {reason}（最近 {count} 次）')

    lessons = [
        '# Lessons Learned（自動整理）',
        '',
        f'- 更新時間：{datetime.date.today().isoformat()}',
        f"- 近期事件統計：{', '.join([f'{k}={v}' for k, v in event_counts.items()])}",
        '',
        '## 回答前必做',
        '- 優先回答使用者核心問題，避免離題。',
        '- 若知識不足，直接回覆資料不足，不可補完推測。',
        '- 涉及規則/課程/組織時先查 club_manual，查不到就明確拒答。',
        '',
        '## 最近高頻失敗提醒',
    ]
    if top_issue_lines:
        lessons.extend(top_issue_lines)
    else:
        lessons.append('- 目前尚無重複錯誤。')

    troubleshooting = [
        '# Troubleshooting（自動整理）',
        '',
        f'- 更新時間：{datetime.date.today().isoformat()}',
        '',
        '## 重複錯誤與建議處理',
    ]
    if top_issue_lines:
        troubleshooting.extend(top_issue_lines)
        troubleshooting.extend([
            '',
            '## 建議',
            '- 若同類錯誤連續發生，先檢查對應知識檔是否缺資料。',
            '- 將新資訊先記錄到 pending review，不直接併入正式 knowledge。',
        ])
    else:
        troubleshooting.append('- 目前尚無可整理的重複錯誤。')

    try:
        with open(paths['lessons'], 'w', encoding='utf-8') as f:
            f.write('\n'.join(lessons) + '\n')
        with open(paths['troubleshooting'], 'w', encoding='utf-8') as f:
            f.write('\n'.join(troubleshooting) + '\n')
    except Exception as e:
        logger.error('Failed to write lessons/troubleshooting: %s', e)


def load_pre_answer_lessons(config, logger, max_chars=3000):
    paths = get_learning_paths(config)
    if not os.path.exists(paths['lessons']):
        return ''
    try:
        with open(paths['lessons'], 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if len(content) > max_chars:
                return content[-max_chars:]
            return content
    except Exception as e:
        logger.error('Failed to load lessons file: %s', e)
        return ''


def parse_learned_tags(ai_response):
    return re.findall(r'<LEARNED>(.*?)</LEARNED>', ai_response or '', re.IGNORECASE | re.DOTALL)
