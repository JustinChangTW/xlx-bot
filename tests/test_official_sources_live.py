import os
import unittest
from types import SimpleNamespace
from urllib.parse import urljoin

import requests

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

from xlxbot.providers import ProviderService


LIVE_OFFICIAL_SOURCES = [
    'https://tmc1974.com/',
    'https://tmc1974.com/schedule/',
    'https://tmc1974.com/presidents/',
    'https://tmc1974.com/leaders/',
    'https://tmc1974.com/board-members/',
    'https://www.instagram.com/taipeitoastmasters/',
    'https://www.youtube.com/@1974toastmaster/videos',
    'https://www.facebook.com/tmc1974',
    'https://www.flickr.com/photos/133676498@N06/albums/',
]

CORE_TMC_SOURCES = {
    'https://tmc1974.com/',
    'https://tmc1974.com/schedule/',
    'https://tmc1974.com/presidents/',
    'https://tmc1974.com/leaders/',
    'https://tmc1974.com/board-members/',
}

ACCESS_LIMITED_SOCIAL_STATUSES = {400, 401, 403, 429}

CORE_PAGE_DEEP_CONTENT_EXPECTATIONS = {
    'https://tmc1974.com/': [
        '健言51週年社慶',
        '157期社長盃',
    ],
    'https://tmc1974.com/schedule/': [
        '會外會活動',
        '社拓活動',
        '50種課程規劃',
    ],
    'https://tmc1974.com/presidents/': [
        '第十八期',
        '第十六期',
        '社刊發起人',
    ],
    'https://tmc1974.com/leaders/': [
        '攝影組長',
        '公關組長',
        '社拓組長',
    ],
    'https://tmc1974.com/board-members/': [
        '常務監事',
        '監 事',
        '社團架構 Architecture',
    ],
}


@unittest.skipUnless(
    os.getenv('RUN_LIVE_OFFICIAL_SOURCE_TESTS') == '1',
    'Set RUN_LIVE_OFFICIAL_SOURCE_TESTS=1 to run live official-source checks.',
)
@unittest.skipUnless(BS4_AVAILABLE, 'BeautifulSoup4 is required for live official-source checks.')
class LiveOfficialSourceTestCase(unittest.TestCase):
    def setUp(self):
        self.provider = ProviderService(
            config=SimpleNamespace(gemini_api_key=''),
            state=object(),
            logger=object(),
        )
        self.headers = self.provider._build_browser_headers()

    def _fetch_soup(self, url):
        response = requests.get(url, timeout=15, headers=self.headers)
        if url in CORE_TMC_SOURCES:
            response.raise_for_status()
        else:
            self.assertIn(
                response.status_code,
                {200, *ACCESS_LIMITED_SOCIAL_STATUSES},
                f'Unexpected social platform status for {url}: {response.status_code}',
            )
        self.assertIn('text/html', response.headers.get('content-type', ''))
        return response.url, BeautifulSoup(response.content, 'lxml')

    def _approved_links_from_page(self, soup, base_url, max_links=40):
        links = []
        seen = set()
        for anchor in soup.find_all('a', href=True, limit=240):
            href = urljoin(base_url, anchor['href'])
            if href in seen or not self.provider._is_approved_official_url(href):
                continue
            seen.add(href)
            text = self.provider._clean_text_line(anchor.get_text(' ', strip=True)) or '(no text)'
            links.append((text, href))
            if len(links) >= max_links:
                break
        return links

    def _deep_page_text(self, soup):
        container = soup.find('main') or soup.find('article') or soup.find('body') or soup
        texts = []
        for element in container.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td', 'th'], limit=800):
            text = self.provider._clean_text_line(element.get_text(' ', strip=True))
            if text:
                texts.append(text)
        tail = texts[len(texts) // 2:]
        return '\n'.join(tail or texts)

    def _all_page_links(self, soup, base_url, max_links=160):
        links = []
        seen = set()
        for anchor in soup.find_all('a', href=True, limit=500):
            href = urljoin(base_url, anchor['href'])
            if href in seen:
                continue
            seen.add(href)
            text = self.provider._clean_text_line(anchor.get_text(' ', strip=True)) or '(no text)'
            links.append((text, href))
            if len(links) >= max_links:
                break
        return links

    def test_live_official_sources_are_reachable_and_expose_official_links(self):
        for source_url in LIVE_OFFICIAL_SOURCES:
            with self.subTest(source_url=source_url):
                final_url, soup = self._fetch_soup(source_url)
                self.assertTrue(self.provider._is_approved_official_url(final_url), final_url)

                title = self.provider._clean_text_line(soup.title.get_text(' ', strip=True) if soup.title else '')
                self.assertTrue(title, f'Missing page title for {source_url}')

                if source_url in CORE_TMC_SOURCES:
                    links = self._approved_links_from_page(soup, final_url)
                    self.assertGreaterEqual(
                        len(links),
                        1,
                        f'Expected at least one approved official hyperlink on {source_url}',
                    )

    def test_tmc_homepage_links_to_core_official_pages(self):
        final_url, soup = self._fetch_soup('https://tmc1974.com/')
        links = {href for _, href in self._approved_links_from_page(soup, final_url, max_links=80)}

        expected_links = {
            'https://tmc1974.com/schedule/',
            'https://tmc1974.com/presidents/',
            'https://tmc1974.com/leaders/',
            'https://tmc1974.com/board-members/',
        }
        self.assertTrue(
            expected_links.issubset(links),
            f'Missing expected official links: {sorted(expected_links - links)}',
        )

    def test_core_official_pages_expose_deep_scroll_content(self):
        for source_url, expected_terms in CORE_PAGE_DEEP_CONTENT_EXPECTATIONS.items():
            with self.subTest(source_url=source_url):
                _, soup = self._fetch_soup(source_url)
                deep_text = self._deep_page_text(soup)
                for term in expected_terms:
                    self.assertIn(
                        term,
                        deep_text,
                        f'Expected deep page content {term!r} on {source_url}',
                    )

    def test_core_official_pages_have_footer_or_deep_links(self):
        for source_url in CORE_TMC_SOURCES:
            with self.subTest(source_url=source_url):
                final_url, soup = self._fetch_soup(source_url)
                all_links = self._all_page_links(soup, final_url)
                tail_links = all_links[len(all_links) // 2:]
                approved_tail_links = [
                    href for _, href in tail_links
                    if self.provider._is_approved_official_url(href)
                ]
                self.assertGreaterEqual(
                    len(approved_tail_links),
                    1,
                    f'Expected at least one approved official hyperlink in lower half of {source_url}',
                )


if __name__ == '__main__':
    unittest.main()
