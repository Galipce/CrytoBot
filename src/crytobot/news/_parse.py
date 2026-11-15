"""Yanıt gövdesi → ham öğeler (spec 0046 R-5; plan Risk 4, 7, 8, 9).

RSS 2.0 ve Atom `xml.parsers.expat` ile okunur: iç ya da dış her varlık bildirimi ve dış varlık
başvurusu `xml_entity`, bozuk XML `bad_xml`, RSS ya da Atom olmayan belge `bad_schema`. Varlıksız
düz DOCTYPE kabul edilir. Öğe çocuğu olmayan alanın metni olduğu gibi alınır (CDATA ya da
kaçırılmış HTML); karışık içerik (Atom `type="xhtml"`, satır içi öğeli açıklama) belge sırasıyla,
işaretlemesiyle yeniden yazılır (review round 1 F-1). Binance duyuru listesi katı şemayla okunur:
sapma `bad_schema`, bozuk JSON ya da UTF-8 `bad_json`. İçerik hiçbir biçimde çalıştırılmaz;
bağlantılar izlenmez.
"""

import html
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.parsers import expat

from crytobot.news._items import RawItem

BINANCE_LINK = "https://www.binance.com/en/support/announcement/"
_SEP = " "
_ATOM = "http://www.w3.org/2005/Atom"
_CONTENT = "http://purl.org/rss/1.0/modules/content/"


class ParseError(Exception):
    """Ayrıştırılamayan ya da reddedilen içerik; `name` hata adıdır (plan Risk 12)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def _local(name: str) -> str:
    return name.rsplit(_SEP, 1)[-1]


@dataclass
class _Node:
    """Öğe: `content` metin parçaları ve çocuk öğeler, belge sırasıyla."""

    name: str
    attrs: dict[str, str]
    content: list["str | _Node"] = field(default_factory=list)

    @property
    def children(self) -> list["_Node"]:
        return [each for each in self.content if isinstance(each, _Node)]

    @property
    def text(self) -> str:
        """Çocuğu yoksa metin olduğu gibi; karışık içerik işaretlemesiyle (F-1)."""
        if not self.children:
            return "".join(each for each in self.content if isinstance(each, str))
        return "".join(_markup(each) for each in self.content)

    def child(self, name: str) -> "_Node | None":
        return next((each for each in self.children if each.name == name), None)

    def child_text(self, name: str) -> str | None:
        node = self.child(name)
        return None if node is None else node.text


def _markup(part: "str | _Node") -> str:
    if isinstance(part, str):
        return html.escape(part, quote=False)
    attrs = "".join(
        f' {_local(key)}="{html.escape(value, quote=True)}"' for key, value in part.attrs.items()
    )
    inner = "".join(_markup(each) for each in part.content)
    return f"<{_local(part.name)}{attrs}>{inner}</{_local(part.name)}>"


def _refuse_entity(*_args: object) -> None:
    raise ParseError("xml_entity")


def _tree(body: bytes) -> _Node:
    parser = expat.ParserCreate(namespace_separator=_SEP)
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    root = _Node("", {})
    stack = [root]

    def start(name: str, attrs: dict[str, str]) -> None:
        node = _Node(name, attrs)
        stack[-1].content.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        stack.pop()

    def chars(data: str) -> None:
        stack[-1].content.append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.EntityDeclHandler = _refuse_entity
    parser.UnparsedEntityDeclHandler = _refuse_entity
    parser.ExternalEntityRefHandler = _refuse_entity  # type: ignore[assignment]
    try:
        parser.Parse(body, True)
    except expat.ExpatError:
        raise ParseError("bad_xml") from None
    except RecursionError:
        raise ParseError("bad_xml") from None
    if len(root.children) != 1:
        raise ParseError("bad_xml")
    return root.children[0]


def _rfc822(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        moment = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if moment.tzinfo is None:  # "-0000" and offsetless times are unreadable (plan Risk 8)
        return None
    return moment.astimezone(UTC)


def _iso(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    try:
        return moment.astimezone(UTC)
    except OverflowError:
        return None


def _body_or_summary(body: str | None, summary: str | None) -> str:
    if body is not None and body.strip():
        return body
    return summary or ""


def _rss(channel: _Node) -> list[RawItem]:
    items = []
    for node in channel.children:
        if node.name != "item":
            continue
        items.append(
            RawItem(
                node.child_text("guid"),
                node.child_text("link"),
                node.child_text("title") or "",
                _body_or_summary(
                    node.child_text(f"{_CONTENT}{_SEP}encoded"), node.child_text("description")
                ),
                _rfc822(node.child_text("pubDate")),
            )
        )
    return items


def _atom_link(entry: _Node) -> str | None:
    for node in entry.children:
        if node.name == f"{_ATOM}{_SEP}link" and node.attrs.get("rel", "alternate") == "alternate":
            return node.attrs.get("href")
    return None


def _atom(feed: _Node) -> list[RawItem]:
    items = []
    for entry in feed.children:
        if entry.name != f"{_ATOM}{_SEP}entry":
            continue
        published = entry.child_text(f"{_ATOM}{_SEP}published")
        if published is None:
            published = entry.child_text(f"{_ATOM}{_SEP}updated")
        items.append(
            RawItem(
                entry.child_text(f"{_ATOM}{_SEP}id"),
                _atom_link(entry),
                entry.child_text(f"{_ATOM}{_SEP}title") or "",
                _body_or_summary(
                    entry.child_text(f"{_ATOM}{_SEP}content"),
                    entry.child_text(f"{_ATOM}{_SEP}summary"),
                ),
                _iso(published),
            )
        )
    return items


def parse_feed(body: bytes) -> list[RawItem]:
    """RSS 2.0 ya da Atom akışının öğeleri, belge sırasıyla."""
    return _feed(_tree(body))


def _feed(root: _Node) -> list[RawItem]:
    if root.name == "rss":
        channel = root.child("channel")
        if channel is None:
            raise ParseError("bad_schema")
        return _rss(channel)
    if root.name == f"{_ATOM}{_SEP}feed":
        return _atom(root)
    raise ParseError("bad_schema")


def _bad_schema() -> ParseError:
    return ParseError("bad_schema")


def _release(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise _bad_schema()
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return None  # unreadable: written with the time unknown (R-4)


def _article(raw: object) -> RawItem:
    if not isinstance(raw, dict):
        raise _bad_schema()
    article_id, code, title = raw.get("id"), raw.get("code"), raw.get("title")
    if not isinstance(article_id, int) or isinstance(article_id, bool):
        raise _bad_schema()
    # the code becomes part of the link: ASCII letters and digits only reach a URL
    if not isinstance(code, str) or not (code.isascii() and code.isalnum()):
        raise _bad_schema()
    if not isinstance(title, str):
        raise _bad_schema()
    return RawItem(
        str(article_id), f"{BINANCE_LINK}{code}", title, "", _release(raw.get("releaseDate"))
    )


def parse_binance(body: bytes) -> list[RawItem]:
    """`data.catalogs[].articles[]` öğeleri, yanıt sırasıyla (plan Risk 9)."""
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ParseError("bad_json") from None
    data = document.get("data") if isinstance(document, dict) else None
    catalogs = data.get("catalogs") if isinstance(data, dict) else None
    if not isinstance(catalogs, list):
        raise _bad_schema()
    items: list[RawItem] = []
    for catalog in catalogs:
        articles = catalog.get("articles") if isinstance(catalog, dict) else None
        if not isinstance(articles, list):
            raise _bad_schema()
        items.extend(_article(article) for article in articles)
    return items


PARSERS: dict[str, Callable[[bytes], list[RawItem]]] = {
    "rss": parse_feed,
    "binance-duyuru": parse_binance,
}
