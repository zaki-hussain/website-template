#!/usr/bin/env python3
"""Minimal static-site build.

Assembles a self-contained, deployable site into ``dist/``:

* copies the static assets (``css/``, ``media/``) verbatim;
* reads person-specific content from ``config.toml`` (name, socials, about,
  playground links) and injects it into ``index.html``;
* converts each Markdown source in ``content/writings/*.md`` to a standalone
  HTML page in ``dist/writings/`` using ``templates/post.html``, builds the
  Writing list on the home page, and writes an RSS feed to ``dist/feed.xml``.

Optional: if ``config.toml`` has ``birthdate = "YYYY-MM-DD"``, the build
computes age and substitutes ``{{age}}`` in config strings (e.g. about text).

The repo itself is a generic template: everything personal lives in
``config.toml`` + ``content/writings/`` + ``media/``. Only the contents of
``dist/`` are meant to be served, so the sources are never exposed on the web.

Run it whenever you change config or add a writing:

    python3 build.py

Markdown files whose name starts with ``_`` (e.g. ``_template.md``) are ignored.
"""

from __future__ import annotations

import re
import shutil
import sys
import tomllib
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

try:
    import markdown
except ModuleNotFoundError:
    sys.exit(
        "The 'markdown' package is required. Install it with:\n"
        "    pip install -r requirements.txt"
    )

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"
CONTENT_DIR = ROOT / "content" / "writings"
TEMPLATE_PATH = ROOT / "templates" / "post.html"
INDEX_SRC = ROOT / "index.html"

DIST = ROOT / "dist"
DIST_WRITINGS = DIST / "writings"

# Top-level static files/directories copied verbatim into the build output.
STATIC_ASSETS = ["css", "media"]

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            "Missing config.toml. Copy config.example.toml to config.toml and edit it."
        )
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def compute_age(birthdate: object) -> str | None:
    """Return age as a string from ``YYYY-MM-DD``, or None if unset."""
    if birthdate is None or str(birthdate).strip() == "":
        return None
    raw = str(birthdate).strip()
    try:
        born = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        sys.exit(f"Invalid birthdate {raw!r}; expected YYYY-MM-DD.")
    today = date.today()
    age = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        age -= 1
    return str(age)


def apply_age(text: str, age: str | None) -> str:
    """Replace ``{{age}}`` when a birthdate was provided."""
    if "{{age}}" not in text:
        return text
    if age is None:
        sys.exit(
            "{{age}} appears in config but birthdate is missing. "
            'Add birthdate = "YYYY-MM-DD" to config.toml.'
        )
    return text.replace("{{age}}", age)


def replace_region(text: str, region: str, inner_lines: list[str]) -> str:
    """Replace the content between ``<!-- REGION:START -->`` / ``:END`` markers,
    preserving the markers and their indentation."""
    pattern = re.compile(
        rf"([ \t]*)(<!-- {region}:START.*?-->).*?(<!-- {region}:END -->)",
        re.DOTALL,
    )
    if not pattern.search(text):
        sys.exit(f"Missing {region}:START/END markers in index.html.")

    def repl(match: re.Match) -> str:
        indent = match.group(1)
        body = "\n".join(indent + line for line in inner_lines)
        return f"{indent}{match.group(2)}\n{body}\n{indent}{match.group(3)}"

    return pattern.sub(repl, text)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a ``key: value`` front-matter block from the Markdown body."""
    meta: dict[str, str] = {}
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return meta, text
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, text[match.end():]


def render_markdown(body: str) -> str:
    md = markdown.Markdown(
        extensions=["extra", "sane_lists", "smarty"],
        output_format="html5",
    )
    return md.convert(body)


def build_post(md_path: Path, template: str, name: str) -> dict[str, str]:
    meta, body = parse_front_matter(md_path.read_text(encoding="utf-8"))
    slug = md_path.stem
    title = meta.get("title", slug)
    date = meta.get("date", "")
    description = meta.get("description", title)

    html = (
        template.replace("{{title}}", escape(title))
        .replace("{{date}}", escape(date))
        .replace("{{description}}", escape(description))
        .replace("{{name}}", escape(name))
        .replace("{{body}}", render_markdown(body))
    )

    DIST_WRITINGS.mkdir(parents=True, exist_ok=True)
    (DIST_WRITINGS / f"{slug}.html").write_text(html, encoding="utf-8")
    return {"slug": slug, "title": title, "date": date, "description": description}


def socials_lines(socials: list[dict]) -> list[str]:
    lines = []
    for social in socials:
        href = escape(str(social.get("href", "")))
        label = escape(str(social.get("label", "")))
        icon = escape(str(social.get("icon", "")))
        lines.append(
            f'<a href="{href}" aria-label="{label}">'
            f'<img class="icon" src="media/{icon}" alt="{label}"></a>'
        )
    return lines


def about_lines(about: list[str], age: str | None) -> list[str]:
    lines = []
    for paragraph in about:
        text = apply_age(str(paragraph), age)
        lines.append(f"<p>{escape(text)}</p>")
    return lines


def playground_lines(playground: list[str], domain: str) -> list[str]:
    domain = escape(str(domain))
    lines = []
    for sub in playground:
        sub = escape(str(sub))
        lines.append(
            f'<li><a href="https://{sub}.{domain}/" target="_blank" rel="noopener">'
            f'{sub}<span class="tld">.{domain}</span></a></li>'
        )
    return lines


def writing_lines(posts: list[dict[str, str]]) -> list[str]:
    if not posts:
        return ['<li class="list-empty">No braindumps yet</li>']
    ordered = sorted(posts, key=lambda p: (p["date"], p["title"]), reverse=True)
    return [
        f'<li><a href="writings/{p["slug"]}.html">{escape(p["title"])}</a>'
        f'<span class="list-note">{escape(p["date"])}</span></li>'
        for p in ordered
    ]


def rfc822_date(date_str: str) -> str:
    """Convert ``YYYY-MM-DD`` to an RFC 822 date for RSS ``pubDate``."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return date_str
    return format_datetime(dt)


def build_feed(config: dict, posts: list[dict[str, str]]) -> None:
    name = str(config.get("name", ""))
    domain = str(config.get("domain", ""))
    site = f"https://{domain}"
    ordered = sorted(posts, key=lambda p: (p["date"], p["title"]), reverse=True)

    items = []
    for post in ordered:
        link = f"{site}/writings/{post['slug']}.html"
        items.append(
            "\n".join(
                [
                    "    <item>",
                    f"      <title>{xml_escape(post['title'])}</title>",
                    f"      <link>{xml_escape(link)}</link>",
                    f"      <guid isPermaLink=\"true\">{xml_escape(link)}</guid>",
                    f"      <pubDate>{xml_escape(rfc822_date(post['date']))}</pubDate>",
                    f"      <description>{xml_escape(post['description'])}</description>",
                    "    </item>",
                ]
            )
        )

    feed = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0">',
            "  <channel>",
            f"    <title>{xml_escape(name)}</title>",
            f"    <link>{xml_escape(site)}/</link>",
            f"    <description>Writings by {xml_escape(name)}</description>",
            *items,
            "  </channel>",
            "</rss>",
            "",
        ]
    )
    (DIST / "feed.xml").write_text(feed, encoding="utf-8")


def build_index(config: dict, posts: list[dict[str, str]], age: str | None) -> None:
    text = INDEX_SRC.read_text(encoding="utf-8")

    text = replace_region(text, "SOCIALS", socials_lines(config.get("socials", [])))
    text = replace_region(
        text, "ABOUT", about_lines(config.get("about", []), age)
    )
    text = replace_region(
        text,
        "PLAYGROUND",
        playground_lines(config.get("playground", []), config.get("domain", "")),
    )
    text = replace_region(text, "WRITING", writing_lines(posts))

    text = text.replace("{{name}}", escape(str(config.get("name", ""))))
    note = apply_age(str(config.get("playground_note", "")), age)
    text = text.replace("{{playground_note}}", escape(note))

    (DIST / "index.html").write_text(text, encoding="utf-8")


def copy_static_assets() -> None:
    for name in STATIC_ASSETS:
        src = ROOT / name
        if not src.exists():
            continue
        dest = DIST / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)


def main() -> None:
    if not TEMPLATE_PATH.exists():
        sys.exit(f"Missing template: {TEMPLATE_PATH}")
    config = load_config()
    age = compute_age(config.get("birthdate"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    name = str(config.get("name", ""))

    # Start from a clean output directory so nothing stale is ever served.
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    copy_static_assets()

    sources = sorted(
        p for p in CONTENT_DIR.glob("*.md") if not p.name.startswith("_")
    )
    posts = [build_post(path, template, name) for path in sources]
    build_index(config, posts, age)
    build_feed(config, posts)

    print(f"Built site into {DIST.name}/ ({len(posts)} writing(s)):")
    for post in sorted(posts, key=lambda p: p["date"], reverse=True):
        print(f"  - {post['date']}  {post['title']}  ->  {DIST.name}/writings/{post['slug']}.html")
    print(f"  feed -> {DIST.name}/feed.xml")
    if age is not None:
        print(f"  age  -> {age} (from birthdate)")
    if not posts:
        print("  (no writings yet — home page shows 'No braindumps yet')")


if __name__ == "__main__":
    main()
