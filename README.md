# Website Template

A config-driven personal site. Everything personal lives in `config.toml`, `content/writings/`, and `media/` — the build writes a static site to `dist/`, which is the only thing you serve.

```bash
cp config.example.toml config.toml   # then edit it
pip install -r requirements.txt
python3 build.py                     # rebuilds dist/ from scratch
```

## config.toml

Top level:

- `name` — page heading and title
- `logo` — favicon filename in `media/`
- `domain` — used for the RSS feed URL and subdomain lists
- `birthdate` — `YYYY-MM-DD`, enables `{{age}}`
- `[[socials]]` — header icons: `label`, `href`, `icon` (filename in `media/`)

## Sections

Each `[[section]]` is a collapsible block on the home page (first one open by default). A section is just a `title` and a `text` body written in Markdown; inline HTML passes through untouched.

```toml
[[section]]
title = "About"
text = """
Anything in **Markdown**, with <em>inline HTML</em> if you want.
"""
```

Placeholders usable anywhere in `text`:

- `{{age}}` — age computed from `birthdate`
- `{{writings}}` — the post list from `content/writings/` plus an RSS link (also enables `feed.xml`)
- `{{subdomains}}` — renders the section's `subdomains` list; each prefix links to `https://<prefix>.<domain>/` with the `.<domain>` part greyed out. If you omit the placeholder, the list is appended after the text.

```toml
[[section]]
title = "Playground"
text = "Small things I made."
subdomains = ["demo", "notes"]   # -> demo.example.com, notes.example.com

[[section]]
title = "Writing"
text = "{{writings}}"
```

## Writings

Markdown files in `content/writings/`, one page each under `dist/writings/`. Files starting with `_` are ignored. Front matter:

```md
---
title: My post
date: 2026-01-01
description: One-liner used in the RSS feed
---

Body in Markdown.
```
