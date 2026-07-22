__author__ = 'Khiem Doan'
__github__ = 'https://github.com/khiemdoan'
__email__ = 'doankhiem.crazy@gmail.com'

from datetime import date, datetime
import json
from pathlib import Path
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup
from cloudscraper import CloudScraper

from dtos import Bingo18Result, Bingo18ResultList

URL = 'https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-bingo18'
RENDER_INFO_URL = 'https://vietlott.vn/ajaxpro/Vietlott.Utility.WebEnvironments,Vietlott.Utility.ashx'
DRAW_RESULT_URL = 'https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameBingoCompareWebPart,Vietlott.PlugIn.WebParts.ashx'
DATA_DIR = Path('data/bingo18')
PAGE_SIZE = 6
MAX_PAGES_PER_FETCH = 100
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)


class _Http:
    """Plain ``requests.Session`` first, fall back to ``cloudscraper``.

    Vietlott sits behind Cloudflare but does not always require a JS
    challenge. Plain requests with a real browser User-Agent succeeds
    on most runners; when Cloudflare blocks with HTTP 403/503 we
    transparently retry through cloudscraper with exponential backoff.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi,en;q=0.9',
        })
        self._scraper: CloudScraper | None = None
        self._last_status: int | None = None

    def _scraper_instance(self) -> CloudScraper:
        if self._scraper is None:
            self._scraper = CloudScraper()
            self._scraper.headers.update({
                'User-Agent': USER_AGENT,
                'Accept-Language': 'vi,en;q=0.9',
            })
        return self._scraper

    def get(self, url: str, **kwargs):
        return self._request('GET', url, **kwargs)

    def post(self, url: str, data, **kwargs):
        return self._request('POST', url, data=data, **kwargs)

    def _request(self, method: str, url: str, **kwargs):
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            response = self._session.request(method, url, **kwargs)
            self._last_status = response.status_code
            if response.status_code in (403, 503):
                # Cloudflare challenged us; switch to cloudscraper with backoff.
                scraper = self._scraper_instance()
                response = scraper.request(method, url, data=kwargs.get('data'), **{
                    k: v for k, v in kwargs.items() if k != 'data'
                })
                self._last_status = response.status_code
                if response.status_code in (403, 503):
                    sleep_seconds = 5 * (attempt + 1)
                    time.sleep(sleep_seconds)
                    last_exc = RuntimeError(
                        f'Vietlott blocked request to {url} '
                        f'(HTTP {response.status_code}); retry {attempt + 1}/{MAX_RETRIES}'
                    )
                    continue
            return response
        if last_exc is not None:
            raise last_exc
        return response


class Bingo18:
    def __init__(self) -> None:
        self._http = _Http()
        self._data: dict[tuple[date, int], Bingo18Result] = {}
        self._raw_data: pd.DataFrame = pd.DataFrame()
        self._render_info: dict | None = None

    def load(self) -> None:
        path = DATA_DIR / 'bingo18.json'
        if not path.exists():
            return
        with path.open('r', encoding='utf-8') as f:
            data = Bingo18ResultList.model_validate_json(f.read())
        for d in data.root:
            self._data[(d.date, d.draw_id)] = d
        self.generate_dataframe()

    def _get_render_info(self) -> dict:
        if self._render_info is not None:
            return self._render_info

        page = self._http.get(URL, timeout=REQUEST_TIMEOUT)
        page.raise_for_status()
        response = self._http.post(
            RENDER_INFO_URL,
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'X-AjaxPro-Method': 'ServerSideFrontEndCreateRenderInfo',
                'Referer': URL,
            },
            data=json.dumps({'SiteId': 'main.frontend.vi'}),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json().get('value')
        if not isinstance(payload, dict) or not payload.get('SiteId'):
            raise RuntimeError('Vietlott returned an invalid render context')
        self._render_info = payload
        return payload

    def _fetch_page(self, page_index: int) -> BeautifulSoup:
        response = self._http.post(
            DRAW_RESULT_URL,
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'X-AjaxPro-Method': 'ServerSideDrawResult',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': 'https://vietlott.vn',
                'Referer': URL,
            },
            data=json.dumps({
                'ORenderInfo': self._get_render_info(),
                'GameId': '8',
                'GameDrawNo': '',
                'number': '',
                'DrawDate': '',
                'PageIndex': page_index,
                'TotalRow': 0,
            }),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        value = response.json().get('value')
        if not isinstance(value, dict) or value.get('Error'):
            message = value.get('InfoMessage') if isinstance(value, dict) else None
            raise RuntimeError(message or 'Vietlott rejected the Bingo18 Ajax request')
        html = value.get('HtmlContent')
        if not html:
            raise RuntimeError('Vietlott returned no Bingo18 result HTML')
        return BeautifulSoup(html, 'lxml')

    @staticmethod
    def _parse_row(row) -> Bingo18Result | None:
        cells = row.find_all('td')
        if len(cells) != 4:
            return None
        date_links = cells[0].find_all('a')
        if len(date_links) < 2:
            return None
        try:
            parsed_date = datetime.strptime(date_links[0].get_text(strip=True), '%d/%m/%Y').date()
            draw_id = int(date_links[1].get_text(strip=True).lstrip('#'))
        except ValueError:
            return None

        balls_div = cells[1].find('div', class_='CssDivBingo')
        if balls_div is None:
            return None
        ball_spans = balls_div.select('span.bong_tron_bingo') or balls_div.find_all('span')
        try:
            balls = [int(span.get_text(strip=True)) for span in ball_spans if span.get_text(strip=True).isdigit()]
        except ValueError:
            return None
        if len(balls) != 3:
            return None

        total_text = cells[2].get_text(' ', strip=True)
        total_match = re.search(r'\d+', total_text)
        if total_match is None:
            return None
        return Bingo18Result(
            date=parsed_date,
            draw_id=draw_id,
            ball_1=balls[0],
            ball_2=balls[1],
            ball_3=balls[2],
            total=int(total_match.group()),
            verdict=cells[3].get_text(' ', strip=True),
        )

    def fetch(self) -> list[Bingo18Result]:
        """Fetch new Bingo18 draws, paging until existing data is reached.

        Vietlott exposes six draws per Ajax page. Fetching continues past the
        first page when the local cache is behind, which prevents a missed
        polling cycle from permanently losing draws.
        """
        fetched: list[Bingo18Result] = []
        for page_index in range(MAX_PAGES_PER_FETCH):
            soup = self._fetch_page(page_index)
            rows = soup.select('table.table-hover > tbody > tr')
            if not rows:
                break

            page_contains_cached_draw = False
            for row in rows:
                result = self._parse_row(row)
                if result is None:
                    continue
                key = (result.date, result.draw_id)
                if key in self._data:
                    page_contains_cached_draw = True
                    continue
                self._data[key] = result
                fetched.append(result)

            if page_contains_cached_draw or len(rows) < PAGE_SIZE:
                break

        self.generate_dataframe()
        return fetched

    def generate_dataframe(self) -> None:
        records = [d.model_dump() for d in self._data.values()]
        self._raw_data = pd.DataFrame(records)
        if not self._raw_data.empty:
            self._raw_data['date'] = pd.to_datetime(self._raw_data['date'])
            for col in ('ball_1', 'ball_2', 'ball_3', 'total'):
                self._raw_data[col] = self._raw_data[col].astype('int64')
            self._raw_data['draw_id'] = self._raw_data['draw_id'].astype('int64')

    def dump(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        records = sorted(
            (d.model_dump() for d in self._data.values()),
            key=lambda r: (r['date'], r['draw_id']),
        )
        result_list = Bingo18ResultList.model_validate([Bingo18Result(**r) for r in records])

        df = pd.DataFrame(records)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])

        with open(DATA_DIR / 'bingo18.json', 'w', encoding='utf-8') as f:
            f.write(result_list.model_dump_json(indent=2))

        df.to_csv(DATA_DIR / 'bingo18.csv', index=False)
        df.to_parquet(DATA_DIR / 'bingo18.parquet', index=False)

    def get_raw_data(self) -> pd.DataFrame:
        return self._raw_data

    def get_last_draw_id(self) -> int | None:
        if not self._data:
            return None
        return max(d.draw_id for d in self._data.values())


if __name__ == '__main__':
    bingo = Bingo18()
    bingo.load()
    new = bingo.fetch()
    if new:
        print(f'Fetched {len(new)} new draw(s).')
        for r in new:
            print(f'  {r.date} #{r.draw_id}: {r.ball_1}-{r.ball_2}-{r.ball_3} '
                  f'sum={r.total} {r.verdict}')
    else:
        print('No new draws found.')

    bingo.dump()
    print(f'Total draws stored: {len(bingo._data)}')
    print(f'Last draw id: {bingo.get_last_draw_id()}')
