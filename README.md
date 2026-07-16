# Website Template

## Setup

```bash
git clone https://github.com/zaki-hussain/website-template.git mysite
cd mysite
cp config.example.toml config.toml   # edit it
pip install -r requirements.txt
python3 build.py                     # outputs to dist/
```

Or to use it in an existing repo, add the template as a remote and pull updates when it changes:

```bash
git remote add template https://github.com/zaki-hussain/website-template.git
git fetch template
git merge template/main
```

Put your favicon + social icons in `media/`, posts in `content/writings/` (markdown, files starting with `_` are ignored), then rerun `python3 build.py`. Serve `dist/` only.

## Config

Everything personal lives in `config.toml`. Values are plain text — HTML/markdown is escaped; markdown only works in `content/writings/`.

- `name`, `domain`, `logo` (favicon filename in `media/`), `birthdate`
- `{{age}}` in any paragraph/note is replaced with the age computed from `birthdate`
- `[[socials]]` — header icons: `label`, `href`, `icon` (filename in `media/`)
- `[[section]]` — home page sections, in order. Each needs `type` + `title`, optional `note`:
  - `text` — `paragraphs`, a list of strings
  - `links` — `items`, a list of `{label, href}`
  - `subdomains` — `items`, a list of prefixes linking to `https://<prefix>.<domain>/`
  - `writing` — the post list from `content/writings/` + RSS feed
