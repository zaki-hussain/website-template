# Website Template

A config-driven personal site. Everything personal lives in `config.toml`, `content/writing/`, and `media/` (plus any extra paths in `include`) — the build writes a static site to `dist/`, which is the only thing you serve.

```bash
cp config.example.toml config.toml   # then edit it
pip install -r requirements.txt
python3 build.py                     # rebuilds dist/ from scratch
```

## config.toml

Top level:

- `name` — page heading and title
- `logo` — favicon filename in `media/`
- `rss_icon` — RSS icon filename in `media/` (defaults to `rss.svg`; shown with `{{writing}}`)
- `domain` — site domain for the RSS feed and for `{{subdomains: ...}}`
- `birthdate` — `YYYY-MM-DD`, enables `{{age}}`
- `include` — optional list of extra top-level directories/files to copy into `dist/` alongside `css/` and `media/` (e.g. `include = ["library"]`)
- `[[socials]]` — header icons: `label`, `href`, `icon` (filename in `media/`)

## Sections

Each `[[section]]` is a collapsible block on the home page (first one open by default). A section is just a `title` and a `text` body written in Markdown; inline HTML passes through untouched.

```toml
[[section]]
title = "About"
text = """
Anything in **Markdown**, with <em>inline HTML</em> if you want.
I am {{age}}.
"""
```

Placeholders usable anywhere in `text`:

- `{{age}}` — age computed from `birthdate`
- `{{writing}}` — the post list from `content/writing/` plus an RSS icon linking to `feed.xml` (also enables the feed)
- `{{subdomains: demo, notes}}` — a link for each prefix on the top-level `domain` (`demo.example.com`, …), with the `.<domain>` part greyed out

```toml
[[section]]
title = "Playground"
text = """
Small things I made.

{{subdomains: demo, notes}}
"""

[[section]]
title = "Writing"
text = "{{writing}}"
```

## Writing

Markdown files in `content/writing/`, one page each under `dist/writing/`. Files starting with `_` are ignored. Front matter:

```md
---
title: My post
date: 2026-01-01
description: One-liner used in the RSS feed
---

Body in Markdown.
```
