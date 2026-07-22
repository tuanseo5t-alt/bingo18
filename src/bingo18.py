__author__ = 'Khiem Doan'
__github__ = 'https://github.com/khiemdoan'
__email__ = 'doankhiem.crazy@gmail.com'

from datetime import date, datetime
from itertools import cycle
import json
import os
from pathlib import Path
import random
import re
import time

import pandas as pd
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from dtos import Bingo18Result, Bingo18ResultList

URL = 'https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-bingo18'
RENDER_INFO_URL = 'https://vietlott.vn/ajaxpro/Vietlott.Utility.WebEnvironments,Vietlott.Utility.ashx'
DRAW_RESULT_URL = 'https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameBingoCompareWebPart,Vietlott.PlugIn.WebParts.ashx'
DATA_DIR = Path('data/bingo18')
PAGE_SIZE = 6
MAX_PAGES_PER_FETCH = 100
REQUEST_TIMEOUT = 30
# Order matters: prefer the most recent Chrome profile, then fall back.
IMPERSONATE_BROWSERS = ('chrome133', 'chrome131', 'chrome124', 'edge101', 'safari17_0')
# Cloudflare/Vietlott returns 403 on blocked IPs (very common from GitHub
# Actions runners). When that happens we rotate to the next browser profile
# and optionally to a new proxy before retrying.
MAX_ATTEMPTS_PER_REQUEST = 5
RETRY_BACKOFF_BASE = 1.5  # seconds; multiplied per attempt


def _parse_proxies(value: str | None) -> list[str]:
    """Parse the proxy list from an env var.

    Accepts either ``HTTP_PROXY``/``HTTPS_PROXY`` style single URLs or a
    semicolon-separated list in ``BINGO18_PROXIES``. Empty/whitespace
    entries are dropped. Used to mask GitHub Actions runner IPs from
    Cloudflare's IP reputation scoring.
    """
    if not value:
        return []
    parts = [p.strip() for p in value.replace('\n', ';').split(';')]
    return [p for p in parts if p]


class _Http:
    """HTTP client with Chrome TLS fingerprint via curl_cffi.

    Vietlott sits behind Cloudflare and rejects Python's default TLS
    fingerprint, the ``cloudscraper`` ClientHello, and even ``curl_cffi``
    impersonating ``chrome124``. To buy a few more weeks we:

    1. Try a newer impersonate profile first (``chrome133``),
       then fall back through older ones.
    2. Optionally rotate through a configured proxy pool so each
       connection looks like it comes from a different residential IP.
    3. Back off and retry on 403/503 from Cloudflare.
    """

    def __init__(self) -> None:
        # Read proxy pool once at construction. Each successful request
        # remembers the proxy it used so the whole render-info / draw
        # call shares the same egress IP (Cloudflare ties the Ajax call
        # cookies to the page-fetch IP).
        proxies_env = os.environ.get('BINGO18_PROXIES') or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        self._proxies = _parse_proxies(proxies_env)
        self._default_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi,en;q=0.9',
        }

    def _build_session(self, impersonate: str, proxy: str | None) -> curl_requests.Session:
        session = curl_requests.Session(impersonate=impersonate)
        session.headers.update(self._default_headers)
        if proxy:
            session.proxies = {'http': proxy, 'https': proxy}
        return session

    def _attempt_order(self, exclude: tuple[str, ...] = ()) -> list[tuple[str, str | None]]:
        """Yield ``(impersonate, proxy)`` pairs to try in order.

        If no proxies are configured the proxy component is ``None``
        for every pair. The first item is the preferred browser; if
        it fails we rotate to the next browser (same proxy), and only
        rotate the proxy when we are about to start a new session.
        """
        browsers = [b for b in IMPERSONATE_BROWSERS if b not in exclude]
        if not self._proxies:
            return [(b, None) for b in browsers]
        proxy_cycle = cycle(self._proxies)
        pairs = []
        for b in browsers:
            pairs.append((b, next(proxy_cycle)))
        return pairs

    def request(self, method: str, url: str, **kwargs):
        """Issue a GET/POST with impersonate + proxy rotation and retry.

        Retries on any ``curl_cffi`` transport/HTTP error. Each retry
        rotates to a new browser profile; if multiple proxies are
        configured the proxy rotates too.
        """
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        last_exc: Exception | None = None
        attempts = self._attempt_order()
        for idx, (impersonate, proxy) in enumerate(attempts[:MAX_ATTEMPTS_PER_REQUEST]):
            session = self._build_session(impersonate, proxy)
            try:
                response = session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except Exception as exc:  # noqa: BLE001 - we want to catch any transport error
                last_exc = exc
                sleep_for = (RETRY_BACKOFF_BASE ** idx) + random.uniform(0, 0.5)
                time.sleep(min(sleep_for, 8.0))
            finally:
                try:
                    session.close()
                except Exception:
                    pass
        assert last_exc is not None
        raise last_exc

    def get(self, url: str, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url: str, data=None, **kwargs):
        if data is not None and not isinstance(data, (str, bytes, bytearray)):
            data = json.dumps(data)
        return self.request('POST', url, data=data, **kwargs)


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

        self._http.get(URL, timeout=REQUEST_TIMEOUT)
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
