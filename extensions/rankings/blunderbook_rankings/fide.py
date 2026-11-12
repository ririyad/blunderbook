"""FIDE's monthly rating lists (ROADMAP 16.1): read one list's zip and keep only the players
the tab can show.

Endpoints, checked on 2026-11-12 at https://ratings.fide.com/download_lists.phtml (the
November 2026 lists were dated 11 Nov 2026; a new month's lists come out around the 1st):

- https://ratings.fide.com/download/standard_rating_list_xml.zip  (about 14 MB)
- https://ratings.fide.com/download/rapid_rating_list_xml.zip     (about 12 MB)
- https://ratings.fide.com/download/blitz_rating_list_xml.zip     (about 8 MB)

Each zip holds one XML file, ``<playerslist>`` with one ``<player>`` per rated player:
``fideid``, ``name``, ``country``, ``sex``, ``title`` ("GM", "IM", ...), ``w_title``
("WGM", ...), ``o_title``, ``foa_title``, ``rating``, ``games``, ``k``, ``birthday`` (a year)
and ``flag`` (``i`` or ``wi``: inactive; ``w``: a woman). Checked against a real download on
2026-11-12 (``tests/fixtures/fide_blitz_recorded.xml``): the member is called
``blitz_rating_list.xml`` (90.7 MB), with no month in its name, so the month comes from the
file's Last-Modified date (see ``update.list_month``). An older name with the month in it
(``standard_nov26frl_xml.xml``) is still read.

What's kept (so rankings.db stays small in every backup): active players only, as FIDE's own
top lists are, and of those the world top 100 and each federation's top 50 in each of Open,
Women, Juniors and Girls. Juniors are born in the list's year minus 20 or later.
TODO(verify): FIDE's exact junior rule.
"""

import heapq
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Final, Literal

from blunderbook_rankings.net import Stopped

Speed = Literal["standard", "rapid", "blitz"]
Category = Literal["open", "women", "juniors", "girls"]

SPEEDS: Final[tuple[Speed, ...]] = ("standard", "rapid", "blitz")
CATEGORIES: Final[tuple[Category, ...]] = ("open", "women", "juniors", "girls")
WORLD_TOP: Final = 100
FED_TOP: Final = 50
JUNIOR_AGE: Final = 20
# The XML of the biggest list is about 150 MB. Anything far bigger isn't a rating list (a
# zip bomb, or a different file).
MAX_XML_BYTES: Final = 400 * 1024 * 1024

MONTHS: Final = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_NAMES: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MEMBER_MONTH: Final = re.compile(r"(" + "|".join(MONTHS) + r")(\d{2})frl", re.IGNORECASE)

# FIDE writes some titles as codes in its TXT lists ("g", "wg"); the XML has "GM", "WGM".
TITLES: Final = {
    "g": "GM",
    "wg": "WGM",
    "m": "IM",
    "wm": "WIM",
    "f": "FM",
    "wf": "WFM",
    "c": "CM",
    "wc": "WCM",
}


def url(speed: Speed) -> str:
    return f"https://ratings.fide.com/download/{speed}_rating_list_xml.zip"


def month_label(month: str) -> str:
    """ "2026-11" -> "November 2026"."""
    year, number = month.split("-")
    return f"{MONTH_NAMES[int(number) - 1]} {year}"


class BadList(Exception):
    """A downloaded file that isn't a FIDE rating list. Plain message."""


@dataclass(frozen=True, slots=True)
class Player:
    fide_id: int
    name: str
    fed: str | None
    sex: str | None  # 'M' | 'F'
    title: str | None
    born: int | None
    rating: int
    games: int | None


@dataclass(frozen=True, slots=True)
class FideList:
    speed: Speed
    month: str  # "2026-11"
    players: tuple[Player, ...]  # the ones kept, highest rating first
    read: int  # players in the file
    active: int  # of those, active and rated


def categories(player: Player, year: int) -> Iterator[Category]:
    """The lists ``player`` is in, for a list of ``year``."""
    yield "open"
    woman = player.sex == "F"
    junior = player.born is not None and player.born >= year - JUNIOR_AGE
    if woman:
        yield "women"
    if junior:
        yield "juniors"
    if woman and junior:
        yield "girls"


@dataclass
class Selection:
    """The players to keep, chosen as the file is read: a small heap per list, so memory
    stays flat however many players the file has."""

    year: int
    _heaps: dict[tuple[str | None, Category], list[tuple[int, int, int]]] = field(
        default_factory=dict
    )
    _players: dict[int, Player] = field(default_factory=dict)

    def add(self, player: Player) -> None:
        for category in categories(player, self.year):
            self._push((None, category), player, WORLD_TOP)
            if player.fed:
                self._push((player.fed, category), player, FED_TOP)

    def _push(self, key: tuple[str | None, Category], player: Player, size: int) -> None:
        # Highest rating first; on equal ratings, the lower FIDE ID (as the page sorts).
        item = (player.rating, -player.fide_id, player.fide_id)
        heap = self._heaps.setdefault(key, [])
        if len(heap) < size:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
        else:
            return
        self._players[player.fide_id] = player

    def players(self) -> tuple[Player, ...]:
        kept = {item[2] for heap in self._heaps.values() for item in heap}
        chosen = (self._players[i] for i in kept)
        return tuple(sorted(chosen, key=lambda p: (-p.rating, p.fide_id)))


def read_list(
    path: Path,
    speed: Speed,
    fallback_month: str,
    progress: Callable[[float], None] = lambda _: None,
    stop: Callable[[], bool] = lambda: False,
) -> FideList:
    """Read the list in the zip at ``path``. Its month comes from the file's name, else
    ``fallback_month`` ("YYYY-MM"). Raises BadList, or Stopped when ``stop()`` turns true
    (checked every 1000 players)."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BadList(f"FIDE's {speed} list isn't a zip file.") from exc
    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".xml"):
            raise BadList(f"FIDE's {speed} list should hold one XML file.")
        member = members[0]
        if member.file_size > MAX_XML_BYTES:
            raise BadList(f"FIDE's {speed} list is too big to be a rating list.")
        month = member_month(member.filename) or fallback_month
        selection = Selection(int(month[:4]))
        read = active = 0
        with archive.open(member) as raw:
            counted = _Counted(raw)
            try:
                for player in _players(counted):
                    read += 1
                    if player is not None:
                        active += 1
                        selection.add(player)
                    if read % 1000 == 0:
                        if stop():
                            raise Stopped
                        progress(counted.done / member.file_size if member.file_size else 0.0)
            except ET.ParseError as exc:
                raise BadList(f"FIDE's {speed} list couldn't be read: {exc}.") from exc
            except (zipfile.BadZipFile, EOFError, OSError) as exc:
                raise BadList(f"FIDE's {speed} list is damaged: {exc}.") from exc
    progress(1.0)
    return FideList(speed, month, selection.players(), read, active)


def member_month(name: str) -> str | None:
    """ "standard_nov26frl_xml.xml" -> "2026-11"; None when the name doesn't say."""
    found = _MEMBER_MONTH.search(name)
    if found is None:
        return None
    number = MONTHS.index(found.group(1).lower()) + 1
    return f"20{found.group(2)}-{number:02d}"


def player(fields: dict[str, str]) -> Player | None:
    """One ``<player>``'s fields as a Player, or None when it isn't shown anywhere (inactive,
    unrated, or no ID)."""
    if "i" in fields.get("flag", "").lower():
        return None
    fide_id = _number(fields.get("fideid"))
    rating = _number(fields.get("rating"))
    name = " ".join(fields.get("name", "").split())
    if not fide_id or not rating or not name:
        return None
    sex = fields.get("sex", "").strip().upper()
    fed = fields.get("country", "").strip().upper()
    return Player(
        fide_id=fide_id,
        name=name,
        fed=fed or None,
        sex=sex if sex in ("M", "F") else None,
        title=_title(fields.get("title")) or _title(fields.get("w_title")),
        born=_number(fields.get("birthday")) or None,
        rating=rating,
        games=_number(fields.get("games")),
    )


def _players(source: _Counted) -> Iterator[Player | None]:
    """Each ``<player>`` in the stream, in order, cleared as it's read."""
    events = ET.iterparse(source, events=("start", "end"))
    root: ET.Element | None = None
    for event, elem in events:
        if root is None and event == "start":
            root = elem
        if event == "end" and elem.tag == "player":
            yield player({child.tag: (child.text or "") for child in elem})
            if root is not None:
                root.clear()  # drop the players read so far


def _title(code: str | None) -> str | None:
    text = (code or "").strip()
    if not text:
        return None
    return TITLES.get(text.lower(), text.upper())


def _number(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except ValueError:
        return None


class _Counted:
    """A stream that counts the bytes read, for progress."""

    def __init__(self, raw: IO[bytes]) -> None:
        self.raw = raw
        self.done = 0

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size)
        self.done += len(data)
        return data
