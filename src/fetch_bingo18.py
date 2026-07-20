__author__ = 'Khiem Doan'
__github__ = 'https://github.com/khiemdoan'
__email__ = 'doankhiem.crazy@gmail.com'

"""Fetch Bingo18 lottery results every 7 minutes.

Vietlott draws a Bingo18 round every ~6 minutes. This script polls the
public listing on https://vietlott.vn once per interval, appends any
new draws to data/bingo18.{csv,json,parquet} and keeps running until
interrupted.

Usage:
    python src/fetch_bingo18.py                 # poll every 7 minutes
    python src/fetch_bingo18.py --interval 30   # poll every 30 seconds (testing)
    python src/fetch_bingo18.py --once          # fetch a single time then exit
"""

import argparse
import functools
import signal
import sys
import time
from datetime import datetime, timezone

from bingo18 import Bingo18

DEFAULT_INTERVAL = 420  # 7 minutes (Bingo18 draws are every ~6 minutes; 7 keeps a small overlap)

print = functools.partial(print, flush=True)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def poll(bingo: Bingo18, interval: int) -> None:
    running = True

    def _stop(_signum, _frame):
        nonlocal running
        running = False
        print(f'[{_now_utc()}] Stop signal received; finishing current cycle...')

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f'[{_now_utc()}] Bingo18 fetcher started; polling every {interval} second(s).')
    last_dump_at = 0.0
    while running:
        try:
            new = bingo.fetch()
        except Exception as exc:
            print(f'[{_now_utc()}] Fetch error: {exc!r}; will retry next cycle.', file=sys.stderr)
            new = []

        if new:
            for r in new:
                print(f'[{_now_utc()}] New draw: '
                      f'{r.date.isoformat()} #{r.draw_id} '
                      f'{r.ball_1}-{r.ball_2}-{r.ball_3} '
                      f'sum={r.total} {r.verdict}')
            bingo.dump()
            last_dump_at = time.monotonic()
            print(f'[{_now_utc()}] Saved. Total stored draws: {len(bingo._data)}.')
        elif last_dump_at == 0.0:
            print(f'[{_now_utc()}] No new draws yet; nothing to save.')

        if not running:
            break

        # sleep in 1-second slices so SIGTERM is acted on promptly
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    # Always leave a fresh dump behind on exit.
    bingo.dump()
    print(f'[{_now_utc()}] Stopped. Total stored draws: {len(bingo._data)}.')


def main() -> None:
    parser = argparse.ArgumentParser(description='Poll Vietlott Bingo18 results.')
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                        help=f'Seconds between polls (default: {DEFAULT_INTERVAL} = 7 minutes).')
    parser.add_argument('--once', action='store_true',
                        help='Fetch a single time then exit (useful for back-fills or cron).')
    args = parser.parse_args()

    bingo = Bingo18()
    bingo.load()

    if args.once:
        new = bingo.fetch()
        for r in new:
            print(f'[{_now_utc()}] New draw: '
                  f'{r.date.isoformat()} #{r.draw_id} '
                  f'{r.ball_1}-{r.ball_2}-{r.ball_3} '
                  f'sum={r.total} {r.verdict}')
        bingo.dump()
        print(f'[{_now_utc()}] Done. Total stored draws: {len(bingo._data)}.')
        return

    poll(bingo, max(1, args.interval))


if __name__ == '__main__':
    main()
