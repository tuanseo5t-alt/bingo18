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


class Max3DPrizeRow(BaseModel):
    """One row of the prize table on the right side of the Max 3D page.

    For Max 3D (basic) there are 4 rows: Đặc biệt / Nhất / Nhì / Ba.
    For Max 3D+ (the second tab) there are 5 rows including ``Giải Tư``.
    The fetcher only captures the basic tab.

    ``numbers`` is the textual representation of the drawn numbers for
    that prize tier. For Đặc biệt that's e.g. ``"512 809"`` (2 triplets);
    for Ba it's ``"323 723 277 ..."`` (8 triplets).
    """

    prize: str        # "Giải Đặc biệt" | "Giải Nhất" | "Giải Nhì" | "Giải Ba"
    numbers: str      # triplets separated by spaces
    winner_count: int
    prize_value: int  # VND


class Max3DResult(BaseModel):
    """Single Max 3D draw.

    Draws happen on Mon/Wed/Fri at 18:00 and are broadcast on TodayTV /
    SCTV2. Each draw yields 20 three-digit numbers split across four
    prize tiers: Đặc biệt (2), Nhất (4), Nhì (6), Ba (8).

    Each prize is stored as a list of 3-digit strings, e.g.
    ``["512", "809"]`` for Đặc biệt. The full sequence of 60 digits
    can be reconstructed by flattening all four lists.

    ``draw_id`` is stored as a zero-padded string (``"01107"``) to match
    the format Vietlott displays. Cast with ``int(n)`` when an integer
    is needed.
    """

    date: date
    draw_id: str  # zero-padded, e.g. "01107"
    special: list[str]    # Giải Đặc biệt: 2 three-digit numbers
    prize1: list[str]     # Giải Nhất: 4
    prize2: list[str]     # Giải Nhì: 6
    prize3: list[str]     # Giải Ba: 8
    prizes: list[Max3DPrizeRow]

    @field_validator('special', 'prize1', 'prize2', 'prize3')
    @classmethod
    def _validate_triplet(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 3 or not t.isdigit():
                raise ValueError(f'expected a 3-digit string, got {t!r}')
        return v

    def all_numbers(self) -> list[str]:
        return [*self.special, *self.prize1, *self.prize2, *self.prize3]


class Max3DResultList(RootModel):
    root: list[Max3DResult]


class Mega645PrizeRow(BaseModel):
    """One row of the prize table on the right side of the Mega 6/45 page.

    Schema::

        Giải thưởng | Kết quả | Số lượng giải | Giá trị giải (đồng)
        Jackpot    | O O O O O O | 0 | 16.938.370.500
        ...

    The     Kết quả column on Vietlott's listing shows a literal pattern of
    letter ``O``s — one per matching position (each main ball the player
    must match, plus a separate ``O`` for the bonus ball if that tier
    requires matching the bonus). The ``+`` is just a visual separator
    between the main-ball block and the bonus-ball position. The
    ``Khuyến Khích`` tier uses a special non-standard pattern for
    near-misses. We preserve the text exactly as displayed.

    ``pattern_count`` is the total number of letter ``O`` tokens in
    the pattern, i.e. the total number of positions the player must
    match. For ``"O O O O O"`` it's 5 (5 main balls); for
    ``"O O O O O + O"`` it's 6 (5 main + bonus); for ``"OO + O O +
    O O"`` it's 4 by Vietlott's recovery rule.
    """

    prize: str            # "Jackpot" | "Giải Nhất" | "Giải Nhì" | "Giải Ba"
    pattern: str          # e.g. "O O O O O O"
    pattern_count: int    # 6 / 5 / 4 / 3
    winner_count: int
    prize_value: int      # VND


class Mega645Result(BaseModel):
    """Single Mega 6/45 draw.

    Draws happen Wed/Sat/Sun at 18:00. Each draw yields 6 distinct
    integers in the range 01–45, presented in ascending order on the
    listing page. There are 4 prize tiers: Jackpot (match 6), Nhất
    (match 5), Nhì (match 4), Ba (match 3).

    ``numbers`` is stored as zero-padded 2-digit strings (``"01"``..``"45"``)
    to match the format displayed on Vietlott's listing. Cast with
    ``int(n)`` when an integer is needed.

    ``jackpot_value`` is the rolling jackpot amount (VND) for this
    specific draw, captured from the ``.gt_jackpot`` block on the
    detail page. The three fixed-tier prize values (10M / 300K / 30K)
    live in ``prizes``.

    ``draw_id`` is stored as a zero-padded string (``"01538"``) to match
    the format Vietlott displays.
    """

    date: date
    draw_id: str          # zero-padded, e.g. "01538"
    numbers: list[str]    # 6 distinct two-digit strings, sorted ascending
    jackpot_value: int    # VND
    prizes: list[Mega645PrizeRow]

    @field_validator('numbers')
    @classmethod
    def _validate_numbers(cls, v: list[str]) -> list[str]:
        if len(v) != 6:
            raise ValueError(f'Mega 6/45 requires exactly 6 numbers, got {len(v)}')
        ints = []
        for n in v:
            if len(n) != 2 or not n.isdigit():
                raise ValueError(f'expected a 2-digit string, got {n!r}')
            ints.append(int(n))
        if len(set(ints)) != 6:
            raise ValueError(f'numbers must be distinct, got {v}')
        for n in ints:
            if not 1 <= n <= 45:
                raise ValueError(f'each number must be in 01-45, got {n}')
        if ints != sorted(ints):
            raise ValueError(f'numbers must be sorted ascending, got {v}')
        return v


class Mega645ResultList(RootModel):
    root: list[Mega645Result]



class Lotto535PrizeRow(BaseModel):
    """One row of the prize table on the right side of the Lotto 5/35 page.

    Schema::

        Giải thưởng | Kết quả | Số lượng giải | Giá trị giải (đồng)
        Giải Độc Đắc | O O O O O + O | 0 | 6.948.692.500
        Giải Nhất   | O O O O O | 1 | 10.000.000
        Giải Nhì    | O O O O + O | 9 | 5.000.000
        Giải Ba     | O O O O | 85 | 500.000
        Giải Tư     | O O O + O | 256 | 100.000
        Giải Năm    | O O O | 3.021 | 30.000
        Giải Khuyến Khích | OO + O O + O O | 22.028 | 10.000

    The Kết quả column on Vietlott's listing shows a literal pattern of
    letter ``O``s (one per matching main ball) and ``+`` separators
    marking the bonus-ball position. The special ``Khuyến Khích`` tier
    uses a non-standard pattern (``"OO + O O + O O"``) for near-misses.
    We preserve the text exactly as displayed.

    ``pattern_count`` is the number of O's in the pattern (the number
    of main balls the player must match; the bonus is implied by the
    position of ``+``).
    """

    prize: str            # "Giải Độc Đắc" | "Giải Nhất" | ... | "Giải Khuyến Khích"
    pattern: str          # e.g. "O O O O O + O"
    pattern_count: int    # number of O's
    winner_count: int
    prize_value: int      # VND


class Lotto535Result(BaseModel):
    """Single Lotto 5/35 draw.

    Draws happen daily at 18:00. Each draw yields 5 distinct main
    numbers in the range 01–35 plus 1 bonus number in the same range.
    The main numbers are presented in ascending order on the listing
    page; the bonus number comes after a ``|`` visual separator.

    There are 7 prize tiers: Độc Đắc (5+bonus), Nhất (5), Nhì (4+bonus),
    Ba (4), Tư (3+bonus), Năm (3), Khuyến Khích (special near-miss
    recovery rule).

    ``numbers`` stores the 5 main balls; ``bonus`` stores the bonus
    ball. All numbers are zero-padded 2-digit strings (``"01"``..``"35"``)
    to match Vietlott's display format. Cast with ``int(n)`` when an
    integer is needed.

    ``jackpot_value`` is the rolling jackpot amount (VND) for this
    specific draw, captured from the first row of the prize table on
    the detail page.

    ``draw_id`` is stored as a zero-padded string (``"00774"``) to
    match the format Vietlott displays.
    """

    date: date
    draw_id: str          # zero-padded, e.g. "00774"
    numbers: list[str]    # 5 distinct two-digit strings, sorted ascending
    bonus: str            # one two-digit string
    jackpot_value: int    # VND
    prizes: list[Lotto535PrizeRow]

    @field_validator('numbers')
    @classmethod
    def _validate_numbers(cls, v: list[str]) -> list[str]:
        if len(v) != 5:
            raise ValueError(f'Lotto 5/35 requires exactly 5 main numbers, got {len(v)}')
        ints = []
        for n in v:
            if len(n) != 2 or not n.isdigit():
                raise ValueError(f'expected a 2-digit string, got {n!r}')
            ints.append(int(n))
        if len(set(ints)) != 5:
            raise ValueError(f'main numbers must be distinct, got {v}')
        for n in ints:
            if not 1 <= n <= 35:
                raise ValueError(f'each number must be in 01-35, got {n}')
        if ints != sorted(ints):
            raise ValueError(f'main numbers must be sorted ascending, got {v}')
        return v

    @field_validator('bonus')
    @classmethod
    def _validate_bonus(cls, v: str) -> str:
        if len(v) != 2 or not v.isdigit():
            raise ValueError(f'expected a 2-digit bonus, got {v!r}')
        if not 1 <= int(v) <= 35:
            raise ValueError(f'bonus must be in 01-35, got {v}')
        return v


class Lotto535ResultList(RootModel):
    root: list[Lotto535Result]