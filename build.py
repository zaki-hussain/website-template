#!/usr/bin/env python3
"""Minimal static-site build.

Assembles a self-contained, deployable site into ``dist/``:

* copies the static assets (``css/``, ``media/``, plus any paths listed in
  config ``include``) verbatim;
* reads person-specific content from ``config.toml`` (name, logo, socials, and
  an ordered list of ``[[section]]`` tables) and injects it into ``index.html``;
* renders each ``[[section]]`` with ``templates/section.html`` in config
  order — the first one is expanded by default, the rest collapsed, and all
  share ``name="section"`` so opening one closes the others (no JS needed);
* converts each Markdown source in ``content/writing/*.md`` to a standalone
  HTML page in ``dist/writing/`` using ``templates/post.html``; if a section
  uses ``{{writing}}``, it lists the posts on the home page and an RSS feed
  is written to ``dist/feed.xml`` (skipped otherwise).

A ``[[section]]`` is ``title`` + ``text``, where text is Markdown and inline
HTML passes through untouched. Placeholders inside ``text``:

* ``{{age}}``                   — age computed from top-level ``birthdate``;
* ``{{writing}}``               — the generated post list plus the RSS icon;
* ``{{subdomains: a, b, ...}}`` — link list for those prefixes on the top-level
  ``domain``, with the prefix accent-coloured and ``.<domain>`` greyed out.

The repo itself is a generic template: everything personal lives in
``config.toml`` + ``content/writing/`` + ``media/`` (and any extra paths in
``include``). Only the contents of ``dist/`` are meant to be served, so the
sources are never exposed on the web.

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
CONTENT_DIR = ROOT / "content" / "writing"
TEMPLATE_PATH = ROOT / "templates" / "post.html"
SECTION_TEMPLATE_PATH = ROOT / "templates" / "section.html"
INDEX_SRC = ROOT / "index.html"

DIST = ROOT / "dist"
DIST_WRITING = DIST / "writing"

# Top-level static files/directories always copied verbatim into the build output.
STATIC_ASSETS = ["css", "media"]

# Names that must never be copied into dist/ even if listed in config.
_BLOCKED_INCLUDE_NAMES = frozenset(
    {
        "dist",
        "build.py",
        "config.toml",
        "config.example.toml",
        "requirements.txt",
        "README.md",
        ".git",
        ".gitignore",
    }
)

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            "Missing config.toml. Copy config.example.toml to config.toml and edit it."
        )
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def static_asset_names(config: dict) -> list[str]:
    """Return top-level paths to copy into dist/: css, media, plus config ``include``."""
    extras = config.get("include", [])
    if extras is None:
        extras = []
    if not isinstance(extras, list):
        sys.exit(
            'include must be a list of top-level names, e.g. include = ["library"]'
        )

    names: list[str] = []
    seen: set[str] = set()
    for raw in [*STATIC_ASSETS, *extras]:
        if not isinstance(raw, str) or not raw.strip():
            sys.exit(
                'include entries must be non-empty strings, e.g. include = ["library"]'
            )
        name = raw.strip().rstrip("/\\")
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            sys.exit(
                f"Invalid include {raw!r}: use a top-level name under the repo root "
                '(no paths or ".."), e.g. "library".'
            )
        if name in _BLOCKED_INCLUDE_NAMES or name.startswith("."):
            sys.exit(f"include cannot copy {name!r} into dist/.")
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


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
        body = "\n".join(indent + line if line else "" for line in inner_lines)
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


def build_post(md_path: Path, template: str, name: str, logo: str) -> dict[str, str]:
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
        .replace("{{logo}}", escape(logo))
        .replace("{{body}}", render_markdown(body))
    )

    DIST_WRITING.mkdir(parents=True, exist_ok=True)
    (DIST_WRITING / f"{slug}.html").write_text(html, encoding="utf-8")
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


def writing_lines(posts: list[dict[str, str]]) -> list[str]:
    if not posts:
        return ['<li class="list-empty">No braindumps yet</li>']
    ordered = sorted(posts, key=lambda p: (p["date"], p["title"]), reverse=True)
    return [
        f'<li><a href="writing/{p["slug"]}.html">{escape(p["title"])}</a>'
        f'<span class="list-note">{escape(p["date"])}</span></li>'
        for p in ordered
    ]


# ---------------------------------------------------------------------------
# Section rendering
#
# Each [[section]] in config.toml is just ``title`` + ``text``, where text is
# Markdown (inline HTML passes through untouched). Special generated blocks
# are dropped in via placeholders inside the text — see the renderers below.
# ---------------------------------------------------------------------------


def require_field(section: dict, field: str, label: str) -> object:
    value = section.get(field)
    if value is None or value == "" or value == []:
        sys.exit(f"{label}: missing required field {field!r}.")
    return value


def render_writing_block(ctx: dict) -> str:
    """``{{writing}}``: the generated post list plus the RSS icon."""
    icon = escape(str(ctx.get("rss_icon") or "rss.svg"))
    return "\n".join(
        [
            '<p class="rss-link">'
            '<a href="feed.xml" aria-label="RSS">'
            f'<img src="media/{icon}" alt="">'
            "RSS</a></p>",
            '<ul class="list">',
            *("    " + line for line in writing_lines(ctx["posts"])),
            "</ul>",
        ]
    )


SUBDOMAINS_TOKEN_RE = re.compile(
    r"(?:<p>\s*)?\{\{subdomains:\s*([^}]+?)\}\}(?:\s*</p>)?"
)


def render_subdomains_block(items: list[str], ctx: dict, label: str) -> str:
    """Prefixes linking to ``https://<prefix>.<domain>/``, with the prefix
    accent-coloured and ``.<domain>`` greyed out."""
    domain = str(ctx.get("domain") or "").strip()
    if not domain:
        sys.exit(
            f"{label}: {{{{subdomains: ...}}}} needs the top-level domain setting. "
            'Add domain = "example.com" to config.toml.'
        )
    lines = ['<ul class="list list--plain">']
    for prefix in items:
        href = escape(f"https://{prefix}.{domain}/")
        text = f'{escape(prefix)}<span class="tld">.{escape(domain)}</span>'
        lines.append(
            f'    <li><a href="{href}" target="_blank" rel="noopener">{text}</a></li>'
        )
    lines.append("</ul>")
    return "\n".join(lines)


def expand_subdomains(html: str, ctx: dict, label: str) -> str:
    """Swap ``{{subdomains: a, b, ...}}`` for the generated link list."""

    def repl(match: re.Match) -> str:
        items = [part.strip() for part in match.group(1).split(",") if part.strip()]
        if not items:
            sys.exit(f"{label}: {{{{subdomains: ...}}}} needs at least one prefix.")
        return render_subdomains_block(items, ctx, label)

    return SUBDOMAINS_TOKEN_RE.sub(repl, html)


def replace_block_token(html: str, token: str, block_html: str) -> str:
    """Swap ``{{token}}`` for generated block HTML, unwrapping the ``<p>``
    that Markdown adds when the placeholder stands on its own line."""
    pattern = re.compile(rf"<p>\s*\{{\{{{token}\}}\}}\s*</p>|\{{\{{{token}\}}\}}")
    return pattern.sub(lambda _: block_html, html)


def render_section(section: dict, index: int, template: str, ctx: dict) -> list[str]:
    label = f"config.toml [[section]] #{index + 1}"
    if not isinstance(section, dict):
        sys.exit(f"{label}: expected a table ([[section]]), got {type(section).__name__}.")

    title = str(require_field(section, "title", label))
    text = str(require_field(section, "text", label))

    body = render_markdown(apply_age(text, ctx["age"]))

    if "{{writing}}" in body:
        body = replace_block_token(body, "writing", render_writing_block(ctx))
    body = expand_subdomains(body, ctx, label)

    indented = "\n".join(
        "        " + line if line else "" for line in body.splitlines()
    )
    html = (
        template.replace("{{open}}", " open" if index == 0 else "")
        .replace("{{title}}", escape(title))
        .replace("{{body}}", indented)
    )
    return html.splitlines()


def sections_lines(sections: list[dict], ctx: dict) -> list[str]:
    if not sections:
        sys.exit("config.toml has no [[section]] entries; add at least one.")
    template = SECTION_TEMPLATE_PATH.read_text(encoding="utf-8")
    lines: list[str] = []
    for index, section in enumerate(sections):
        if lines:
            lines.append("")
        lines.extend(render_section(section, index, template, ctx))
    return lines


def has_writing_block(sections: list[dict]) -> bool:
    return any(
        isinstance(section, dict) and "{{writing}}" in str(section.get("text", ""))
        for section in sections
    )


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
        link = f"{site}/writing/{post['slug']}.html"
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
    sections = config.get("section", [])
    ctx = {
        "age": age,
        "posts": posts,
        "domain": str(config.get("domain", "")),
        "rss_icon": str(config.get("rss_icon", "rss.svg")),
    }

    text = replace_region(text, "SOCIALS", socials_lines(config.get("socials", [])))
    text = replace_region(text, "SECTIONS", sections_lines(sections, ctx))

    # The RSS feed only exists when {{writing}} is used somewhere, so drop
    # the <link rel="alternate" ...> from the head otherwise.
    if not has_writing_block(sections):
        text = re.sub(r'[ \t]*<link rel="alternate"[^>]*/?>\n', "", text)

    text = text.replace("{{name}}", escape(str(config.get("name", ""))))
    text = text.replace("{{logo}}", escape(str(config.get("logo", "logo.jpg"))))

    (DIST / "index.html").write_text(text, encoding="utf-8")


def copy_static_assets(names: list[str], *, required: set[str] | None = None) -> None:
    """Copy top-level ``names`` into dist/. Missing built-ins are skipped; missing
    config ``include`` entries are errors."""
    required = required or set()
    for name in names:
        src = ROOT / name
        if not src.exists():
            if name in required:
                sys.exit(
                    f"include lists {name!r}, but {src.relative_to(ROOT)} does not exist."
                )
            continue
        dest = DIST / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)


def main() -> None:
    for path in (TEMPLATE_PATH, SECTION_TEMPLATE_PATH):
        if not path.exists():
            sys.exit(f"Missing template: {path}")
    config = load_config()
    age = compute_age(config.get("birthdate"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    name = str(config.get("name", ""))
    logo = str(config.get("logo", "logo.jpg"))
    with_writing = has_writing_block(config.get("section", []))
    asset_names = static_asset_names(config)
    required_assets = set(asset_names) - set(STATIC_ASSETS)

    # Start from a clean output directory so nothing stale is ever served.
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    copy_static_assets(asset_names, required=required_assets)

    sources = sorted(
        p for p in CONTENT_DIR.glob("*.md") if not p.name.startswith("_")
    )
    posts = [build_post(path, template, name, logo) for path in sources]
    build_index(config, posts, age)
    if with_writing:
        build_feed(config, posts)

    print(f"Built site into {DIST.name}/ ({len(posts)} writing(s)):")
    for post in sorted(posts, key=lambda p: p["date"], reverse=True):
        print(f"  - {post['date']}  {post['title']}  ->  {DIST.name}/writing/{post['slug']}.html")
    if with_writing:
        print(f"  feed -> {DIST.name}/feed.xml")
        if not posts:
            print("  (no writing yet — home page shows 'No braindumps yet')")
    if age is not None:
        print(f"  age  -> {age} (from birthdate)")


if __name__ == "__main__":
    main()
