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
# Profiles are validated at import-time against the installed curl_cffi
# version, so the fetcher never crashes on a newer/older runtime that
# happens to lack the newest profile.
_IMPERSONATE_CANDIDATES = (
    'chrome137', 'chrome136', 'chrome135', 'chrome133', 'chrome131',
    'chrome124', 'edge101', 'safari17_0',
)


def _resolve_impersonate_profiles() -> tuple[str, ...]:
    """Return only impersonate profiles supported by the installed curl_cffi.

    ``Session(impersonate=...)`` does NOT raise when constructed with an
    unknown profile — it only raises when a real request is sent. So we
    drive a tiny HTTPS probe to ``example.com`` and keep profiles that
    return a 2xx/3xx response.
    """
    from curl_cffi import requests as _r
    supported: list[str] = []
    for name in _IMPERSONATE_CANDIDATES:
        try:
            session = _r.Session(impersonate=name)
            resp = session.get('https://example.com/', timeout=8)
            ok = 200 <= resp.status_code < 400
        except Exception:
            ok = False
        finally:
            try:
                session.close()
            except Exception:
                pass
        if ok:
            supported.append(name)
    if not supported:
        raise RuntimeError('No supported curl_cffi impersonate profile found')
    return tuple(supported)


IMPERSONATE_BROWSERS = _resolve_impersonate_profiles()
# Cloudflare/Vietlott returns 403 on blocked IPs (very common from GitHub
# Actions runners). When that happens we rotate to a new browser profile
# and optionally to a new proxy before retrying. Without any proxy at
# all we are limited to rotating browser profiles against the runner IP,
# which is almost always blocked — so the fetcher logs a clear warning.
MAX_ATTEMPTS_PER_REQUEST = 8
RETRY_BACKOFF_BASE = 1.5  # seconds; multiplied per attempt
# Public free-proxy list sources. Each URL must return HTML or text where
# IP:PORT pairs can be parsed. Override via FREE_PROXY_SOURCES env var
# (semicolon-separated). Set to empty string to disable.
DEFAULT_FREE_PROXY_SOURCES = (
    'https://free-proxy-list.net/',
    'https://www.sslproxies.org/',
    'https://geonode.com/free-proxy-list',
)
PROXY_HEALTHCHECK_URL = 'https://vietlott.vn/'
PROXY_HEALTHCHECK_TIMEOUT = 8  # seconds
PROXY_POOL_CACHE = DATA_DIR / '.proxy_pool.json'
PROXY_POOL_TTL = 30 * 60  # seconds — refresh the pool at most every 30 minutes
PROXY_HEALTHCHECK_MAX = 8  # how many proxies to validate before giving up


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


_IP_PORT_RE = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*[:\s]\s*(\d{2,5})')


def _parse_proxy_text(text: str) -> list[str]:
    """Extract ``IP:PORT`` entries from raw HTML or plain text."""
    found: list[str] = []
    for ip, port in _IP_PORT_RE.findall(text):
        if 1 <= int(ip.split('.')[0]) <= 223 and 1 <= int(port) <= 65535:
            found.append(f'http://{ip}:{port}')
    # Deduplicate while preserving order.
    return list(dict.fromkeys(found))


class FreeProxyPool:
    """Lazy, cached pool of public free proxies.

    On first use this scrapes a few well-known free-proxy listing pages,
    parses out ``IP:PORT`` pairs, and probes each one against Vietlott's
    public homepage with a short timeout. Surviving proxies are cached
    to ``data/bingo18/.proxy_pool.json`` for ``PROXY_POOL_TTL`` seconds
    so subsequent fetches don't re-hit the listing sites.

    The pool is **best-effort**: free proxies are slow and frequently
    die. We treat it as a supplement to user-supplied ``BINGO18_PROXIES``
    (which always wins) and fall back to direct egress when nothing works.
    """

    def __init__(self) -> None:
        self._lock_path = PROXY_POOL_CACHE.with_suffix('.lock')
        self._pool: list[str] = []
        self._loaded_at: float = 0.0

    def proxies(self) -> list[str]:
        """Return cached healthy proxies, refreshing if stale or empty."""
        if self._pool and (time.time() - self._loaded_at) < PROXY_POOL_TTL:
            return self._pool

        cached = self._load_cache()
        if cached:
            self._pool = cached
            self._loaded_at = time.time()
            return self._pool

        fresh = self._harvest_and_check()
        if fresh:
            self._pool = fresh
            self._loaded_at = time.time()
            self._save_cache()
        return self._pool

    def invalidate(self, bad: str) -> None:
        """Drop a proxy that just failed, persisting the new pool."""
        if bad in self._pool:
            self._pool = [p for p in self._pool if p != bad]
            self._save_cache()

    def _load_cache(self) -> list[str]:
        try:
            with PROXY_POOL_CACHE.open('r', encoding='utf-8') as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        fetched_at = payload.get('fetched_at', 0)
        if (time.time() - fetched_at) > PROXY_POOL_TTL:
            return []
        return [p for p in payload.get('proxies', []) if p]

    def _save_cache(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = {'fetched_at': time.time(), 'proxies': self._pool}
            with PROXY_POOL_CACHE.open('w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
        except OSError:
            # Caching is best-effort; never crash the fetcher over it.
            pass

    def _harvest_and_check(self) -> list[str]:
        sources_env = os.environ.get('FREE_PROXY_SOURCES')
        if sources_env is not None:
            sources = tuple(s.strip() for s in sources_env.split(';') if s.strip())
            enabled = bool(sources)
        else:
            sources = DEFAULT_FREE_PROXY_SOURCES
            enabled = True
        if not enabled:
            return []

        candidates: list[str] = []
        for url in sources:
            try:
                resp = curl_requests.get(url, impersonate='chrome131', timeout=15)
            except Exception:  # noqa: BLE001
                continue
            if resp.status_code != 200:
                continue
            candidates.extend(_parse_proxy_text(resp.text))
            # Stop after we already have a comfortable batch.
            if len(candidates) >= 60:
                break

        # Randomize so different fetcher invocations try different proxies.
        random.shuffle(candidates)
        survivors: list[str] = []
        for proxy in candidates:
            if self._probe(proxy):
                survivors.append(proxy)
                if len(survivors) >= PROXY_HEALTHCHECK_MAX:
                    break
        return survivors

    @staticmethod
    def _probe(proxy: str) -> bool:
        try:
            # Pick the most-supported Chrome profile across curl_cffi
            # versions. We probe the homepage, not the Ajax endpoint,
            # so any 2xx/3xx is a green light.
            impersonate = IMPERSONATE_BROWSERS[0]
            resp = curl_requests.get(
                PROXY_HEALTHCHECK_URL,
                impersonate=impersonate,
                proxies={'http': proxy, 'https': proxy},
                timeout=PROXY_HEALTHCHECK_TIMEOUT,
                allow_redirects=True,
            )
        except Exception:  # noqa: BLE001
            return False
        # Vietlott returns 200/301 for the homepage on a good IP, 403/503
        # on a banned IP. Anything in 2xx/3xx is good enough for us.
        return 200 <= resp.status_code < 400


class _Http:
    """HTTP client with Chrome TLS fingerprint via curl_cffi.

    Vietlott sits behind Cloudflare and rejects Python's default TLS
    fingerprint, the ``cloudscraper`` ClientHello, and even ``curl_cffi``
    impersonating ``chrome124``. To buy a few more weeks we:

    1. Try a newer impersonate profile first (``chrome133``),
       then fall back through older ones.
    2. Optionally rotate through a configured proxy pool so each
       connection looks like it comes from a different residential IP.
       The pool is seeded from ``BINGO18_PROXIES`` and supplemented by
       ``FreeProxyPool`` (auto-scraped public proxies).
    3. Back off and retry on 403/503 from Cloudflare.
    """

    def __init__(self) -> None:
        # Read static proxy pool from environment. Each successful request
        # remembers the proxy it used so the whole render-info / draw
        # call shares the same egress IP (Cloudflare ties the Ajax call
        # cookies to the page-fetch IP).
        proxies_env = os.environ.get('BINGO18_PROXIES') or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
        self._static_proxies = _parse_proxies(proxies_env)
        self._free_pool = FreeProxyPool()
        # Emit a one-line warning at start-up so operators immediately
        # see when the fetcher is running "naked" on a likely-blocked IP
        # (most commonly the GitHub Actions shared range).
        if not self._static_proxies and not self._free_pool.proxies():
            print(
                'WARNING: no proxy configured. Direct egress from this IP is '
                'very likely blocked by Cloudflare (HTTP 403). Set the '
                'BINGO18_PROXIES environment variable / repository secret '
                'to a semicolon-separated list of http://user:pass@host:port '
                'entries to fix this.',
                flush=True,
            )
        self._default_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi,en;q=0.9',
        }

    def _all_proxies(self) -> list[str]:
        """Static pool first, then healthy free proxies appended."""
        seen: set[str] = set()
        ordered: list[str] = []
        for p in self._static_proxies:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        for p in self._free_pool.proxies():
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered

    def _build_session(self, impersonate: str, proxy: str | None) -> curl_requests.Session:
        session = curl_requests.Session(impersonate=impersonate)
        session.headers.update(self._default_headers)
        if proxy:
            session.proxies = {'http': proxy, 'https': proxy}
        return session

    def _attempt_order(self) -> list[tuple[str, str | None]]:
        """Yield ``(impersonate, proxy)`` pairs to try in order.

        If no proxies are configured the proxy component is ``None``
        for every pair. The first item is the preferred browser; if
        it fails we rotate to the next browser (same proxy), and only
        rotate the proxy when we are about to start a new session.
        """
        proxies = self._all_proxies()
        if not proxies:
            return [(b, None) for b in IMPERSONATE_BROWSERS]
        proxy_cycle = cycle(proxies)
        pairs = []
        for b in IMPERSONATE_BROWSERS:
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
                # If this attempt used a free proxy and failed, drop it
                # from the cached pool so the next run avoids it.
                if proxy and proxy not in self._static_proxies:
                    self._free_pool.invalidate(proxy)
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
