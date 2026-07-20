__author__ = 'Khiem Doan'
__github__ = 'https://github.com/khiemdoan'
__email__ = 'doankhiem.crazy@gmail.com'

from datetime import date

from pydantic import BaseModel, RootModel, field_validator


class Result(BaseModel):
    date: date

    special: int

    prize1: int

    prize2_1: int
    prize2_2: int

    prize3_1: int
    prize3_2: int
    prize3_3: int
    prize3_4: int
    prize3_5: int
    prize3_6: int

    prize4_1: int
    prize4_2: int
    prize4_3: int
    prize4_4: int

    prize5_1: int
    prize5_2: int
    prize5_3: int
    prize5_4: int
    prize5_5: int
    prize5_6: int

    prize6_1: int
    prize6_2: int
    prize6_3: int

    prize7_1: int
    prize7_2: int
    prize7_3: int
    prize7_4: int


class ResultList(RootModel):
    root: list[Result]


class Bingo18Result(BaseModel):
    """Single Bingo18 draw.

    A draw happens every ~6 minutes. Each draw yields 3 balls (1..6)
    with a numeric sum and a Lớn/Hòa/Nhỏ verdict on the sum.
    """

    date: date
    draw_id: int
    ball_1: int
    ball_2: int
    ball_3: int
    total: int
    verdict: str  # "Lớn" | "Hòa" | "Nhỏ"


class Bingo18ResultList(RootModel):
    root: list[Bingo18Result]


class KenoResult(BaseModel):
    """Single Keno draw.

    A draw happens every ~10 minutes between 06:00 and 21:52 local time.
    Each draw yields 20 numbers drawn from 1..80. The page also reports
    the even/odd breakdown (Chẵn/Lẻ/Hòa) and the big/small breakdown
    (Lớn/Nhỏ/Hòa) along with the count of numbers in each category.

    Numbers are stored as zero-padded strings (``"00"`` .. ``"80"``) to
    match the format Vietlott displays. Cast with ``int(n)`` when an
    integer is needed. Big/small verdict is split at 40: ``00``–``39`` is
    Nhỏ, ``40``–``80`` is Lớn.
    """

    date: date
    draw_id: int
    numbers: list[str]  # 20 numbers, each a 2-digit string "00".."80"
    even_odd: str        # "Chẵn" | "Lẻ" | "Hòa"
    even_count: int | None
    odd_count: int | None
    big_small: str       # "Lớn" | "Nhỏ" | "Hòa"
    big_count: int | None
    small_count: int | None

    @field_validator('numbers')
    @classmethod
    def _validate_numbers(cls, v: list[str]) -> list[str]:
        if len(v) != 20:
            raise ValueError(f'expected 20 numbers, got {len(v)}')
        for n in v:
            if len(n) != 2 or not n.isdigit():
                raise ValueError(f'number must be 2 digits, got {n!r}')
            i = int(n)
            if i < 0 or i > 80:
                raise ValueError(f'number out of range 0..80: {n!r}')
        return v


class KenoResultList(RootModel):
    root: list[KenoResult]


class Max3DProResult(BaseModel):
    """Single Max 3D Pro draw.

    Draws happen on Tue/Thu/Sat at 18:00 and are broadcast on TodayTV /
    SCTV2. Each draw yields 20 three-digit numbers split across four
    prize tiers: Đặc biệt (2), Nhất (4), Nhì (6), Ba (8).

    Each prize is stored as a list of 3-digit strings, e.g.
    ``["982", "396"]`` for Đặc biệt. The full sequence of 60 digits
    can be reconstructed by flattening all four lists.

    ``draw_id`` is stored as a zero-padded string (``"00753"``) to match
    the format Vietlott displays. Cast with ``int(n)`` when an integer
    is needed.
    """

    date: date
    draw_id: str  # zero-padded, e.g. "00753"
    special: list[str]    # Giải Đặc biệt: 2 three-digit numbers
    prize1: list[str]     # Giải Nhất: 4
    prize2: list[str]     # Giải Nhì: 6
    prize3: list[str]     # Giải Ba: 8

    @field_validator('special', 'prize1', 'prize2', 'prize3')
    @classmethod
    def _validate_triplet(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 3 or not t.isdigit():
                raise ValueError(f'expected a 3-digit string, got {t!r}')
        return v

    def all_numbers(self) -> list[str]:
        return [*self.special, *self.prize1, *self.prize2, *self.prize3]


class Max3DProResultList(RootModel):
    root: list[Max3DProResult]


class Power655PrizeRow(BaseModel):
    """One row of the prize table on the right side of the Power 6/55 page.

    ``numbers`` is the textual representation of the drawn numbers for
    that prize tier (e.g. ``"O O O O O O"`` for Jackpot 1, or
    ``"O O O O O | O"`` for Jackpot 2 where ``|`` separates the bonus).
    Each ``O`` is a placeholder Vietlott uses until you replace it with
    a specific digit.
    """

    prize: str   # "Jackpot 1" | "Jackpot 2" | "Giải Nhất" | ...
    numbers: str # "O O O O O O" / "O O O O O | O" / etc.
    winner_count: int
    prize_value: int  # VND


class Power655Result(BaseModel):
    """Single Power 6/55 draw.

    Draws happen on Wed/Fri/Sun at 18:00. Each draw yields 6 main numbers
    drawn from 1..55 plus 1 bonus "Power Number" (also from 1..55).
    Vietlott also exposes the prize table: who won Jackpot 1 / 2 and how
    many winners + values for each lower tier.

    ``draw_id`` is stored as a zero-padded string (``"01372"``) to match
    the format Vietlott displays.
    """

    date: date
    draw_id: str  # zero-padded, e.g. "01372"
    numbers: list[str]     # 6 main numbers, each "01".."55"
    bonus: str             # bonus "Power Number", "01".."55"
    jackpot1_value: int    # VND, current jackpot 1 value
    jackpot2_value: int    # VND, current jackpot 2 value
    prizes: list[Power655PrizeRow]

    @field_validator('numbers', 'bonus')
    @classmethod
    def _validate_number(cls, v) -> list[str] | str:
        if isinstance(v, str):
            if not v.isdigit() or not 1 <= int(v) <= 55:
                raise ValueError(f'number out of range 1..55: {v!r}')
            return v.zfill(2)
        out = []
        for n in v:
            if not n.isdigit() or not 1 <= int(n) <= 55:
                raise ValueError(f'number out of range 1..55: {n!r}')
            out.append(n.zfill(2))
        if len(out) != 6:
            raise ValueError(f'expected 6 numbers, got {len(out)}')
        if len(set(out)) != 6:
            raise ValueError(f'numbers must be unique, got {v!r}')
        return out


class Power655ResultList(RootModel):
    root: list[Power655Result]
