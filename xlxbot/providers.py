import datetime
import re
from urllib.parse import urljoin, urlparse, urlunparse

import requests

try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    # 沒安裝 Gemini SDK 時仍允許整體服務啟動，只是跳過 Gemini provider。
    GENAI_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


def check_ollama_service(config, logger):
    try:
        # 把 generate API 位址還原成 base URL，單純測服務是否活著。
        parsed_url = urlparse(config.ollama_api_url)
        base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '/', '', '', ''))
        response = requests.get(base_url, timeout=5)
        if response.status_code == 200:
            logger.info('Ollama service is running at %s', base_url)
            return True
        logger.error('Ollama service at %s returned status %s', base_url, response.status_code)
        return False
    except requests.RequestException as e:
        logger.error('Cannot connect to Ollama service at %s: %s', config.ollama_api_url, e)
        return False


def check_ollama_model(config, logger, model_name):
    try:
        parsed_url = urlparse(config.ollama_api_url)
        check_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '/api/show', '', '', ''))
        response = requests.post(check_url, json={'name': model_name}, timeout=10)
        if response.status_code == 200:
            logger.info('Ollama model %s is available', model_name)
            return True
        if response.status_code == 404:
            logger.error('Ollama model "%s" not found on the Ollama server.', model_name)
            logger.error(
                'Please pull the model on the Ollama server machine, e.g., `docker exec -it ollama-server ollama pull %s`',
                model_name
            )
            return False
        logger.error('Ollama model %s check failed with status %s. Response: %s', model_name, response.status_code, response.text[:200])
        return False
    except requests.RequestException as e:
        logger.error('Cannot check Ollama model %s: %s', model_name, e)
        return False


def extract_ollama_response(payload):
    # 兼容不同 provider/格式，把可用文字盡量抽成統一字串。
    if not isinstance(payload, dict):
        return None
    if 'response' in payload and isinstance(payload['response'], str):
        return payload['response']
    if 'completion' in payload and isinstance(payload['completion'], str):
        return payload['completion']
    if 'result' in payload:
        return extract_ollama_response(payload['result'])
    if 'choices' in payload and isinstance(payload['choices'], list) and payload['choices']:
        first = payload['choices'][0]
        if isinstance(first, dict):
            if 'message' in first and isinstance(first['message'], dict):
                return first['message'].get('content')
            return first.get('text') or first.get('content')
    return None


def extract_xai_response(payload):
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get('output_text'), str) and payload.get('output_text').strip():
        return payload['output_text']
    output_items = payload.get('output')
    if isinstance(output_items, list):
        chunks = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            content_items = item.get('content')
            if not isinstance(content_items, list):
                continue
            for content in content_items:
                if not isinstance(content, dict):
                    continue
                text_value = content.get('text')
                if isinstance(text_value, str) and text_value.strip():
                    chunks.append(text_value)
        if chunks:
            return '\n'.join(chunks).strip()
    return extract_ollama_response(payload)


class ProviderService:
    def __init__(self, config, state, logger):
        self.config = config
        self.state = state
        self.logger = logger
        self.gemini_client = genai.Client(api_key=config.gemini_api_key) if GENAI_AVAILABLE and config.gemini_api_key else None

    def is_provider_available(self, provider_name):
        if provider_name == 'groq':
            return bool(self.config.groq_api_key and self.config.groq_model_name)
        if provider_name == 'xai':
            return bool(self.config.xai_api_key and self.config.xai_model_name)
        if provider_name == 'github':
            return bool(self.config.github_models_token and self.config.github_models_name)
        if provider_name == 'gemini':
            return bool(GENAI_AVAILABLE and self.config.gemini_api_key and self.gemini_client)
        if provider_name == 'ollama':
            return bool(self.config.ollama_api_url and self.config.ollama_model_name)
        return False

    def ask_ollama_with_model(self, prompt, model_name):
        try:
            response = requests.post(
                self.config.ollama_api_url,
                json={'model': model_name, 'prompt': prompt, 'stream': False},
                timeout=60
            )
            try:
                response.raise_for_status()
            except requests.HTTPError:
                self.logger.error(
                    'Ollama HTTP error status=%s model=%s response=%s',
                    response.status_code,
                    model_name,
                    response.text[:2000]
                )
                return None

            data = response.json()
            ai_text = extract_ollama_response(data)
            if ai_text:
                self.logger.info('Ollama model %s reply length=%s', model_name, len(ai_text))
                return ai_text
            self.logger.warning('Ollama model %s returned empty response', model_name)
            return None
        except requests.RequestException as e:
            self.logger.error('Ollama request failed for model %s: %s', model_name, e)
            return None
        except ValueError as e:
            self.logger.error('Invalid JSON from Ollama model %s: %s', model_name, e)
            return None

    def ask_ollama(self, prompt):
        return self.ask_ollama_with_model(prompt, self.config.ollama_model_name)

    def ask_openai_compatible_chat(self, api_url, api_key, model_name, prompt, extra_headers=None):
        if not api_key or not model_name:
            return None

        # Groq、GitHub Models 等 OpenAI 相容 API 都走同一套請求格式。
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        if extra_headers:
            headers.update(extra_headers)

        payload = {
            'model': model_name,
            'messages': [
                {'role': 'system', 'content': '你是健言小龍蝦的推理引擎，請使用繁體中文回覆。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.4,
            'stream': False
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=60)
            try:
                response.raise_for_status()
            except requests.HTTPError:
                self.logger.warning(
                    'Provider HTTP error url=%s model=%s status=%s body=%s',
                    api_url,
                    model_name,
                    response.status_code,
                    response.text[:1000]
                )
                return None

            return extract_ollama_response(response.json())
        except requests.RequestException as e:
            self.logger.warning('Provider request failed url=%s model=%s error=%s', api_url, model_name, e)
            return None
        except ValueError as e:
            self.logger.warning('Provider JSON parse failed url=%s model=%s error=%s', api_url, model_name, e)
            return None

    def ask_xai(self, prompt):
        if not self.config.xai_api_key or not self.config.xai_model_name:
            return None
        headers = {'Authorization': f'Bearer {self.config.xai_api_key}', 'Content-Type': 'application/json'}
        payload = {'model': self.config.xai_model_name, 'input': prompt}
        try:
            response = requests.post(self.config.xai_api_url, headers=headers, json=payload, timeout=60)
            try:
                response.raise_for_status()
            except requests.HTTPError:
                self.logger.warning(
                    'xAI HTTP error url=%s model=%s status=%s body=%s',
                    self.config.xai_api_url,
                    self.config.xai_model_name,
                    response.status_code,
                    response.text[:1000]
                )
                return None
            return extract_xai_response(response.json())
        except requests.RequestException as e:
            self.logger.warning('xAI request failed model=%s error=%s', self.config.xai_model_name, e)
            return None
        except ValueError as e:
            self.logger.warning('xAI JSON parse failed model=%s error=%s', self.config.xai_model_name, e)
            return None

    def ask_groq(self, prompt):
        return self.ask_openai_compatible_chat(
            self.config.groq_api_url,
            self.config.groq_api_key,
            self.config.groq_model_name,
            prompt
        )

    def ask_github_models(self, prompt):
        return self.ask_openai_compatible_chat(
            self.config.github_models_api_url,
            self.config.github_models_token,
            self.config.github_models_name,
            prompt,
            extra_headers={
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': self.config.github_models_api_version
            }
        )

    def ask_gemini(self, prompt):
        if not GENAI_AVAILABLE:
            self.logger.warning('genai module not available, skipping Gemini')
            return None
        if not self.config.gemini_api_key or not self.gemini_client:
            self.logger.warning('GEMINI_API_KEY not set, skipping Gemini')
            return None

        try:
            # 逐一嘗試幾個 Gemini 型號，並記住最後一個成功的模型以加快下次命中。
            models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-2.5-pro', 'gemini-2.0-flash-001']
            if self.state.working_gemini_model in models_to_try:
                models_to_try.remove(self.state.working_gemini_model)
                models_to_try.insert(0, self.state.working_gemini_model)

            for model_name in models_to_try:
                try:
                    self.logger.debug('Trying Gemini model: %s', model_name)
                    response = self.gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
                        )
                    )
                    if response.text:
                        self.logger.info('Gemini (%s) reply length=%s', model_name, len(response.text))
                        if self.state.working_gemini_model != model_name:
                            self.state.working_gemini_model = model_name
                            self.logger.info('Cached working Gemini model: %s', self.state.working_gemini_model)
                        return response.text
                    self.logger.warning('Gemini (%s) returned empty response', model_name)
                except Exception as e:
                    self.logger.warning('Gemini model %s failed: %s', model_name, str(e)[:200])
                    continue
            self.logger.error('All Gemini models failed')
            return None
        except Exception as e:
            self.logger.error('Gemini request failed: %s', e)
            return None

    def _build_browser_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def _is_internal_course_query(self, user_input):
        text = (user_input or '').lower()
        keywords = [
            '課程', '課表', '上課', '教育訓練', 'tm', '題目', '社課', '會內會',
            '今天', '明天', '後天', '這週', '這周', '本週', '本周', '下週', '下周', '下一週', '下一周', '下個月', '下个月', '下月'
        ]
        return any(keyword in text for keyword in keywords)

    def _is_news_query(self, user_input):
        text = (user_input or '').lower()
        keywords = ['公告', '最新消息', '會外會', '戶外活動', '活動', '宣傳', '社務布達', '文宣']
        return any(keyword in text for keyword in keywords)

    def _is_official_site_query(self, user_input):
        text = (user_input or '').lower()
        keywords = [
            '社團', '社團簡介', '健言', '小龍蝦', '理事長', '理監事', '高級幹部', '幹部', '社長', '副社長', '組長', '負責人', '講師', '講員', '辯論',
            '活動', '公告', '照片', '相簿', '影片', '影音', '官網', 'leaders', 'board', 'lecturer',
            'debate', 'events', 'photos', 'videos', 'rules'
        ]
        return any(keyword in text for keyword in keywords)

    def _get_official_site_targets(self, user_input, intent):
        text = (user_input or '').lower()
        targets = []

        def add(url):
            if url not in targets:
                targets.append(url)

        if any(keyword in text for keyword in ['社團簡介', '本期高級幹部', '高級幹部']):
            add('https://tmc1974.com/rules/')
            add('https://tmc1974.com/leaders/')
            add('https://tmc1974.com/board-members/')
            add('https://tmc1974.com/')
            return targets[:4]

        if any(keyword in text for keyword in ['理事會成員', '理事會有哪些人', '理監事成員', '理監事有哪些人']):
            add('https://tmc1974.com/board-members/')
            add('https://tmc1974.com/leaders/')
            add('https://tmc1974.com/')
            return targets[:4]

        if re.search(r'\d+\s*期.*(社長|副社長|組長|幹部|負責人)', text):
            add('https://tmc1974.com/leaders/')
            add('https://tmc1974.com/board-members/')
            add('https://tmc1974.com/')
            return targets[:4]

        add('https://tmc1974.com/')
        if any(keyword in text for keyword in ['社團簡介', 'rules', '高級幹部']):
            add('https://tmc1974.com/rules/')

        if any(keyword in text for keyword in ['理事長', '理監事', 'board', '董事', '監事']):
            add('https://tmc1974.com/board-members/')
        if any(keyword in text for keyword in ['幹部', '領導', 'leaders', '社長', '副社長', '組長', '負責人']):
            add('https://tmc1974.com/leaders/')
        if any(keyword in text for keyword in ['講師', 'lecturer', '教育訓練']):
            add('https://tmc1974.com/lecturer/')
        if any(keyword in text for keyword in ['辯論', 'debate']):
            add('https://tmc1974.com/debate/')
        if any(keyword in text for keyword in ['活動', '會外會', 'event', 'events']):
            add('https://tmc1974.com/category/events/')
        if any(keyword in text for keyword in ['照片', '相簿', 'photo', 'photos']):
            add('https://tmc1974.com/category/photos/')
        if any(keyword in text for keyword in ['影片', '影音', 'video', 'videos']):
            add('https://tmc1974.com/category/videos/')

        if intent == 'MEMBER_QUERY':
            add('https://tmc1974.com/rules/')
            add('https://tmc1974.com/board-members/')
            add('https://tmc1974.com/leaders/')
        elif intent == 'ORG_QUERY':
            add('https://tmc1974.com/rules/')
            add('https://tmc1974.com/leaders/')
            add('https://tmc1974.com/board-members/')
        elif intent == 'ACTIVITY_QUERY':
            add('https://tmc1974.com/category/events/')
            add('https://tmc1974.com/category/photos/')
            add('https://tmc1974.com/category/videos/')
        elif intent == 'ANNOUNCEMENT_QUERY':
            add('https://tmc1974.com/category/events/')
        elif intent == 'COURSE_QUERY':
            add('https://tmc1974.com/lecturer/')
            add('https://tmc1974.com/debate/')
        elif intent == 'OVERVIEW':
            add('https://tmc1974.com/rules/')
            add('https://tmc1974.com/leaders/')
            add('https://tmc1974.com/board-members/')
        elif intent == 'GENERAL_OVERVIEW':
            add('https://tmc1974.com/rules/')
            add('https://tmc1974.com/leaders/')
            add('https://tmc1974.com/board-members/')

        return targets[:4]

    def _clean_text_line(self, text):
        cleaned = re.sub(r'\s+', ' ', (text or '')).strip()
        if not cleaned:
            return ''
        if cleaned in {'Read more', '閱讀更多'}:
            return ''
        return cleaned

    def _extract_page_summary(self, url):
        response = requests.get(url, timeout=10, headers=self._build_browser_headers())
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')
        container = soup.find('main') or soup.find('article') or soup.find('body')
        if container is None:
            self.logger.warning('Could not find readable content container on %s', url)
            return None

        lines = []
        seen = set()
        for element in container.find_all(['h1', 'h2', 'h3', 'p', 'li'], limit=80):
            text = self._clean_text_line(element.get_text(' ', strip=True))
            if not text or len(text) < 4:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(text)
            if len(lines) >= 10:
                break

        links = []
        seen_links = set()
        for anchor in container.find_all('a', href=True, limit=40):
            href = urljoin(url, anchor['href'])
            text = self._clean_text_line(anchor.get_text(' ', strip=True))
            if not text or href in seen_links or not href.startswith('https://tmc1974.com/'):
                continue
            seen_links.add(href)
            links.append(f'- {text}: {href}')
            if len(links) >= 5:
                break

        if not lines and not links:
            self.logger.warning('Found page %s but could not extract summary lines', url)
            return None

        title = self._clean_text_line(soup.title.get_text(' ', strip=True) if soup.title else '')
        summary_parts = [f'根據台北市健言社官網頁面（{url}）整理：']
        if title:
            summary_parts.append(f'- 頁面標題：{title}')
        summary_parts.extend(f'- {line}' for line in lines[:8])
        if links:
            summary_parts.append('- 相關連結：')
            summary_parts.extend(links)
        return '\n'.join(summary_parts)

    def query_official_site_map(self, user_input, intent):
        if not BS4_AVAILABLE:
            self.logger.warning('BeautifulSoup4 is not installed. Skipping official site query.')
            return None
        if not self._is_official_site_query(user_input):
            return None

        targets = self._get_official_site_targets(user_input, intent)
        if not targets:
            return None

        summaries = []
        for url in targets:
            try:
                summary = self._extract_page_summary(url)
                if summary:
                    summaries.append(summary)
            except requests.RequestException as e:
                self.logger.warning('Official site query failed for %s: %s', url, e)
            except Exception as e:
                self.logger.warning('Unexpected official site scrape error for %s: %s', url, e)

        if not summaries:
            return None
        return '\n\n'.join(summaries[:3])

    def _next_weekday(self, current_date, weekday):
        days_ahead = (weekday - current_date.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return current_date + datetime.timedelta(days=days_ahead)

    def _extract_requested_schedule_dates(self, user_input):
        text = user_input or ''
        matches = []

        for month, day in re.findall(r'(\d{1,2})\s*/\s*(\d{1,2})', text):
            matches.append(f'{int(month)}/{int(day)}')

        for month, day in re.findall(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', text):
            matches.append(f'{int(month)}/{int(day)}')

        today = datetime.date.today()
        relative_dates = {
            '今天': today,
            '明天': today + datetime.timedelta(days=1),
            '後天': today + datetime.timedelta(days=2),
            # 社課固定周四，提到今天/明天/後天時仍保留明確日曆日期判斷。
        }
        for phrase, resolved_date in relative_dates.items():
            if phrase in text:
                matches.append(f'{resolved_date.month}/{resolved_date.day}')

        normalized = []
        seen = set()
        for item in matches:
            if not item:
                continue
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized

    def _extract_relative_schedule_bucket(self, user_input):
        text = user_input or ''
        if any(keyword in text for keyword in ['下個月', '下个月', '下月']):
            return 'next_month'
        if any(keyword in text for keyword in ['下週', '下周', '下一週', '下一周']):
            return 'next_week'
        if any(keyword in text for keyword in ['這週', '這周', '本週', '本周']):
            return 'this_week'
        return None

    def _normalize_schedule_date(self, date_text, today):
        match = re.search(r'(\d{1,2})\s*/\s*(\d{1,2})', date_text or '')
        if not match:
            return None

        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        try:
            candidate = datetime.date(year, month, day)
        except ValueError:
            return None

        if candidate < today - datetime.timedelta(days=180):
            try:
                candidate = datetime.date(year + 1, month, day)
            except ValueError:
                return None
        return candidate

    def _select_schedule_row_by_relative_bucket(self, rows, bucket, today):
        if not bucket:
            return None

        if bucket == 'this_week':
            week_start = today - datetime.timedelta(days=today.weekday())
            week_end = week_start + datetime.timedelta(days=6)
            for row in rows:
                row_date = row.get('resolved_date')
                if row_date and week_start <= row_date <= week_end and row_date.weekday() == 3:
                    return row

            target_date = self._next_weekday(today - datetime.timedelta(days=1), 3)
            for row in rows:
                if row.get('resolved_date') == target_date:
                    return row
            return None

        if bucket == 'next_week':
            target_date = self._next_weekday(today, 3) + datetime.timedelta(days=7)
            for row in rows:
                if row.get('resolved_date') == target_date:
                    return row
            return None

        if bucket == 'next_month':
            if today.month == 12:
                target_year = today.year + 1
                target_month = 1
            else:
                target_year = today.year
                target_month = today.month + 1

            matched_rows = []
            for row in rows:
                row_date = row.get('resolved_date')
                if row_date is None:
                    continue
                if row_date.year == target_year and row_date.month == target_month and row_date.weekday() == 3:
                    matched_rows.append(row)
            return matched_rows

        return None

    def _build_schedule_row_summary(self, row, url):
        return '\n'.join(
            [
                f'根據台北市健言社官網課表（{url}），{row["date_text"]} 的課程資料如下：',
                f'- 開場主題：{row["opening_topic"]}',
                f'- T.M. 訓練主題：{row["tm_topic"]}',
                f'- 總評：{row["general_evaluator"]}',
                f'- 教育訓練：{row["training_topic"]}',
                f'- 講師：{row["lecturer"]}',
            ]
        )

    def _build_next_month_schedule_summary(self, rows, url):
        lines = [f'根據台北市健言社官網課表（{url}），下個月的周四社課如下：']
        for row in rows:
            lines.extend(
                [
                    f'- {row["date_text"]}',
                    f'  開場主題：{row["opening_topic"]}',
                    f'  T.M. 訓練主題：{row["tm_topic"]}',
                    f'  教育訓練：{row["training_topic"]}',
                ]
            )
        return '\n'.join(lines)

    def _build_fixed_thursday_hint(self, user_input):
        text = user_input or ''
        today = datetime.date.today()
        next_thursday = self._next_weekday(today - datetime.timedelta(days=1), 3)
        if '明天' in text and (today + datetime.timedelta(days=1)).weekday() != 3:
            return f'明天沒有社課，社課固定在每週四；下一次社課是 {next_thursday.month}/{next_thursday.day}。'
        if '今天' in text and today.weekday() != 3:
            return f'今天沒有社課，社課固定在每週四；下一次社課是 {next_thursday.month}/{next_thursday.day}。'
        return None

    def _query_schedule_page(self, user_input):
        fixed_thursday_hint = self._build_fixed_thursday_hint(user_input)
        if fixed_thursday_hint:
            return fixed_thursday_hint

        requested_dates = self._extract_requested_schedule_dates(user_input)
        relative_bucket = self._extract_relative_schedule_bucket(user_input)
        if not requested_dates and not relative_bucket:
            return None

        url = 'https://tmc1974.com/schedule/'
        self.logger.debug('Querying schedule page %s for requested_dates=%s', url, requested_dates)
        response = requests.get(url, timeout=10, headers=self._build_browser_headers())
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')
        table = soup.find('table')
        if not table:
            self.logger.warning('Could not find schedule table on %s', url)
            return None

        today = datetime.date.today()
        parsed_rows = []
        body_rows = table.find_all('tr')
        for row in body_rows:
            cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'])]
            if len(cells) < 6:
                continue
            parsed_rows.append(
                {
                    'date_text': cells[1],
                    'opening_topic': cells[2],
                    'tm_topic': cells[3],
                    'general_evaluator': cells[4],
                    'training_topic': cells[5],
                    'lecturer': cells[6] if len(cells) > 6 else '[未提供]',
                    'resolved_date': self._normalize_schedule_date(cells[1], today),
                }
            )

        matched_row = None
        for row in parsed_rows:
            if row['date_text'] in requested_dates:
                matched_row = row
                break
        if matched_row is None:
            matched_row = self._select_schedule_row_by_relative_bucket(parsed_rows, relative_bucket, today)

        if isinstance(matched_row, list):
            if not matched_row:
                self.logger.info('No schedule rows matched next-month bucket on official schedule page')
                return None
            self.logger.info('Found %d schedule rows for next month on official schedule page', len(matched_row))
            return self._build_next_month_schedule_summary(matched_row, url)

        if matched_row is None:
            self.logger.info('No schedule row matched requested dates=%s relative_bucket=%s', requested_dates, relative_bucket)
            return None

        self.logger.info('Found schedule row for %s on official schedule page', matched_row['date_text'])
        return self._build_schedule_row_summary(matched_row, url)

    def _query_homepage_course_summary(self, user_input):
        url = 'https://tmc1974.com/'
        self.logger.debug('Querying latest courses from %s for: %s', url, user_input)
        response = requests.get(url, timeout=10, headers=self._build_browser_headers())
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')
        posts_container = soup.find('div', class_='elementor-posts-container')
        if not posts_container:
            self.logger.warning('Could not find posts container on the website. The site structure may have changed.')
            return None

        articles = posts_container.find_all('article', class_='elementor-post', limit=5)
        if not articles:
            self.logger.warning('No articles found in the posts container.')
            return None

        scraped_courses = []
        for article in articles:
            title_element = article.find('h3', class_='elementor-post__title')
            date_element = article.find('span', class_='elementor-post-date')
            if title_element and date_element:
                scraped_courses.append(f"- {date_element.get_text(strip=True)}: {title_element.get_text(strip=True)}")

        if scraped_courses:
            course_summary = "根據台北市健言社官網最新公告：\n" + "\n".join(scraped_courses)
            course_summary += f"\n\n更多詳情請訪問官網：{url}"
            self.logger.info('Successfully scraped %d course/event items.', len(scraped_courses))
            return course_summary

        self.logger.warning('Found articles but could not extract title and date.')
        return None

    def query_latest_news(self, user_input):
        if not BS4_AVAILABLE:
            self.logger.warning('BeautifulSoup4 is not installed. Skipping latest news query.')
            return None
        if not self._is_news_query(user_input):
            return None
        try:
            return self._query_homepage_course_summary(user_input)
        except requests.RequestException as e:
            self.logger.error('Error querying latest news from website: %s', e)
        except Exception as e:
            self.logger.error('An unexpected error occurred during latest news scraping: %s', e)
        return None

    def query_course_info(self, user_input):
        if not self._is_internal_course_query(user_input):
            return None
        if not BS4_AVAILABLE:
            self.logger.warning('BeautifulSoup4 is not installed. Skipping dynamic course query.')
            return None

        try:
            schedule_summary = self._query_schedule_page(user_input)
            if schedule_summary:
                return schedule_summary
            return self._query_homepage_course_summary(user_input)
        except requests.RequestException as e:
            self.logger.error('Error querying course info from website: %s', e)
        except Exception as e:
            self.logger.error('An unexpected error occurred during web scraping: %s', e)
        return None
