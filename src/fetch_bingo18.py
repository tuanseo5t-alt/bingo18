"""Poll and persist Bingo18 lottery results.

Vietlott opens Bingo18 from 06:00 through the last draw at 21:53 local
Vietnam time, with a draw approximately every 6 minutes. The GitHub Action
runs this script once every 5 minutes during that window; the fetcher reads
multiple Ajax pages so delayed runs can catch up safely.

Usage:
    python src/fetch_bingo18.py                 # poll every 5 minutes
    python src/fetch_bingo18.py --interval 30   # poll every 30 seconds
    python src/fetch_bingo18.py --once          # fetch once and exit
"""

import argparse
import functools
import signal
import sys
import time
from datetime import datetime, timezone

from bingo18 import Bingo18

DEFAULT_INTERVAL = 300  # GitHub Actions can run at most once every 5 minutes.

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
print = functools.partial(print, flush=True)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _log_new(results) -> None:
    for r in results:
        print(f'[{_now_utc()}] New draw: '
              f'{r.date.isoformat()} #{r.draw_id} '
              f'{r.ball_1}-{r.ball_2}-{r.ball_3} '
              f'sum={r.total} {r.verdict}')


def fetch_once(bingo: Bingo18) -> int:
    new = bingo.fetch()
    _log_new(new)
    bingo.dump()
    print(f'[{_now_utc()}] Saved. New draws: {len(new)}. '
          f'Total stored draws: {len(bingo._data)}.')
    return len(new)


def poll(bingo: Bingo18, interval: int) -> None:
    running = True

    def _stop(_signum, _frame):
        nonlocal running
        running = False
        print(f'[{_now_utc()}] Stop signal received; finishing current cycle...')

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f'[{_now_utc()}] Bingo18 fetcher started; polling every {interval} second(s).')
    while running:
        try:
            fetch_once(bingo)
        except Exception as exc:
            print(f'[{_now_utc()}] Fetch error: {exc!r}; will retry next cycle.', file=sys.stderr)

        if not running:
            break

        # Sleep in 1-second slices so SIGTERM is acted on promptly.
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    bingo.dump()
    print(f'[{_now_utc()}] Stopped. Total stored draws: {len(bingo._data)}.')


def main() -> None:
    parser = argparse.ArgumentParser(description='Poll Vietlott Bingo18 results.')
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                        help=f'Seconds between polls (default: {DEFAULT_INTERVAL} = 5 minutes).')
    parser.add_argument('--once', action='store_true',
                        help='Fetch a single time then exit (useful for GitHub Actions or cron).')
    args = parser.parse_args()

    bingo = Bingo18()
    bingo.load()

    if args.once:
        fetch_once(bingo)
        return

    poll(bingo, max(1, args.interval))


if __name__ == '__main__':
    main()
