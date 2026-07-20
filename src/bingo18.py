__author__ = 'Khiem Doan'
__github__ = 'https://github.com/khiemdoan'
__email__ = 'doankhiem.crazy@gmail.com'

from datetime import date, datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from cloudscraper import CloudScraper

from dtos import Bingo18Result, Bingo18ResultList

URL = 'https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-bingo18'
DATA_DIR = Path('data/bingo18')


class Bingo18:
    def __init__(self) -> None:
        self._http = CloudScraper()
        self._data: dict[tuple[date, int], Bingo18Result] = {}
        self._raw_data: pd.DataFrame = pd.DataFrame()

    def load(self) -> None:
        path = DATA_DIR / 'bingo18.json'
        if not path.exists():
            return
        with path.open('r', encoding='utf-8') as f:
            data = Bingo18ResultList.model_validate_json(f.read())
        for d in data.root:
            self._data[(d.date, d.draw_id)] = d
        self.generate_dataframe()

    def fetch(self) -> list[Bingo18Result]:
        """Fetch the most recent draws from Vietlott's Bingo18 results page.

        Returns the list of newly fetched results (i.e. those whose
        ``(date, draw_id)`` was not already in the cache). The 6 most
        recent draws live on the first page of the listing.
        """
        resp = self._http.get(URL)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, 'lxml')

        output = soup.find('div', class_='doso_keno_output_nd')
        if output is None:
            return []
        rows = output.select('table.table-hover > tbody > tr')
        fetched: list[Bingo18Result] = []
        for row in rows:
            cells = row.find_all('td')
            if len(cells) != 4:
                continue
            date_links = cells[0].find_all('a')
            if len(date_links) < 2:
                continue
            date_text = date_links[0].get_text(strip=True)
            draw_id_text = date_links[1].get_text(strip=True).lstrip('#')
            try:
                parsed_date = datetime.strptime(date_text, '%d/%m/%Y').date()
                draw_id = int(draw_id_text)
            except ValueError:
                continue

            balls_div = cells[1].find('div', class_='CssDivBingo')
            if balls_div is None:
                continue
            balls = [int(span.get_text(strip=True)) for span in balls_div.find_all('span', class_='bong_tron_bingo')]
            if len(balls) != 3:
                continue

            try:
                total = int(cells[2].get_text(strip=True))
            except ValueError:
                continue
            verdict = cells[3].get_text(strip=True)

            result = Bingo18Result(
                date=parsed_date,
                draw_id=draw_id,
                ball_1=balls[0],
                ball_2=balls[1],
                ball_3=balls[2],
                total=total,
                verdict=verdict,
            )
            key = (result.date, result.draw_id)
            if key in self._data:
                continue
            self._data[key] = result
            fetched.append(result)

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
