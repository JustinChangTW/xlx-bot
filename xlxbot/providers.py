import re
from urllib.parse import urlparse, urlunparse

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

    def _extract_requested_schedule_dates(self, user_input):
        text = user_input or ''
        matches = []

        for month, day in re.findall(r'(\d{1,2})\s*/\s*(\d{1,2})', text):
            matches.append(f'{int(month)}/{int(day)}')

        for month, day in re.findall(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日', text):
            matches.append(f'{int(month)}/{int(day)}')

        normalized = []
        seen = set()
        for item in matches:
            if not item:
                continue
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized

    def _query_schedule_page(self, user_input):
        requested_dates = self._extract_requested_schedule_dates(user_input)
        if not requested_dates:
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

        body_rows = table.find_all('tr')
        for row in body_rows:
            cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'])]
            if len(cells) < 6:
                continue
            date_text = cells[1]
            if date_text not in requested_dates:
                continue

            opening_topic = cells[2]
            tm_topic = cells[3]
            general_evaluator = cells[4]
            training_topic = cells[5]
            lecturer = cells[6] if len(cells) > 6 else '[未提供]'

            summary_lines = [
                f'根據台北市健言社官網課表（{url}），{date_text} 的課程資料如下：',
                f'- 開場主題：{opening_topic}',
                f'- T.M. 訓練主題：{tm_topic}',
                f'- 總評：{general_evaluator}',
                f'- 教育訓練：{training_topic}',
                f'- 講師：{lecturer}',
            ]
            self.logger.info('Found schedule row for %s on official schedule page', date_text)
            return '\n'.join(summary_lines)

        self.logger.info('No schedule row matched requested dates=%s', requested_dates)
        return None

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

    def query_course_info(self, user_input):
        course_keywords = ['課程', '課表', '公告', '最新', '活動', 'pathways', 'project', '教育', 'training', '學習', '健言', 'tmc', 'tm', '題目']
        if not any(keyword in user_input.lower() for keyword in course_keywords):
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
