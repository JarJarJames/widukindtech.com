#!/usr/bin/env python3
"""Build beer-updates.html and beer-updates.xml from BEER's GitHub
Discussions "Announcements" category.

Uses GitHub's public REST API, so no token is required. GITHUB_TOKEN is
used if set, for a higher rate limit. Run locally with
`python3 scripts/build_updates.py`. Standard library only.
"""
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OWNER = "JarJarJames"
REPO = "BEER"
CATEGORY_SLUG = "announcements"
AUTHOR = "JarJarJames"  # only show posts by the maintainer
SITE = "https://widukindtech.com"
PAGE = "beer-updates.html"
FEED = "beer-updates.xml"

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "beer-updates.template.html"

API = f"https://api.github.com/repos/{OWNER}/{REPO}/discussions"


def fetch():
    """Read discussions from GitHub's public REST API. A token is optional
    (it only raises the rate limit); the Actions token can't read another
    repo's discussions over GraphQL, but this endpoint works with it."""
    headers = {"Accept": "application/vnd.github.full+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "widukindtech-site-build"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    posts, page = [], 1
    while True:
        req = urllib.request.Request(f"{API}?per_page=100&page={page}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.load(r)
        for d in batch:
            if d["category"]["slug"] != CATEGORY_SLUG:
                continue
            if not d.get("user") or d["user"]["login"] != AUTHOR:
                continue
            posts.append({
                "number": d["number"],
                "title": d["title"],
                "url": d["html_url"],
                "createdAt": d["created_at"],
                "bodyHTML": d.get("body_html") or "",
                "comments": {"totalCount": d.get("comments", 0)},
            })
        if len(batch) < 100:
            break
        page += 1
    posts.sort(key=lambda p: p["createdAt"], reverse=True)
    return posts


PARA = re.compile(r"<p([^>]*)>(.*?)</p>", re.S)
BR = re.compile(r"^(?:\s|<br\s*/?>)+|(?:\s|<br\s*/?>)+$")


def bullets_to_lists(body):
    """Announcements often use typed "•" bullets inside one paragraph.
    Turn those paragraphs into an intro paragraph plus a real list."""
    def fix(m):
        attrs, inner = m.group(1), m.group(2)
        if "•" not in inner:
            return m.group(0)
        head, *items = inner.split("•")
        head = BR.sub("", head)
        items = [BR.sub("", i) for i in items]
        items = [i for i in items if i]
        out = f"<p{attrs}>{head}</p>\n" if head else ""
        return out + "<ul>\n" + "\n".join(f"<li>{i}</li>" for i in items) + "\n</ul>"
    return PARA.sub(fix, body)


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def render_post(p):
    d = parse_date(p["createdAt"])
    pid = f"post-{p['number']}"
    n = p["comments"]["totalCount"]
    comments = f"{n} comment{'s' if n != 1 else ''}" if n else "No comments yet"
    return f"""
      <article class="post" id="{pid}">
        <header>
          <time datetime="{p['createdAt']}">{d.strftime('%B %-d, %Y')}</time>
          <h2><a href="#{pid}">{html.escape(p['title'])}</a></h2>
        </header>
        <div class="post-body">
{bullets_to_lists(p['bodyHTML'])}
        </div>
        <footer>
          <span>{comments}</span>
          <a href="{html.escape(p['url'])}">Discuss on GitHub
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          </a>
        </footer>
      </article>"""


def render_index(posts):
    items = []
    for p in posts:
        d = parse_date(p["createdAt"])
        items.append(
            f'<li><a href="#post-{p["number"]}"><span>{html.escape(p["title"])}</span>'
            f'<time datetime="{p["createdAt"]}">{d.strftime("%b %-d, %Y")}</time></a></li>')
    return "\n".join(items)


def render_feed(posts):
    updated = posts[0]["createdAt"] if posts else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = []
    for p in posts:
        link = f"{SITE}/{PAGE}#post-{p['number']}"
        entries.append(f"""  <entry>
    <title>{html.escape(p['title'])}</title>
    <link href="{link}"/>
    <id>{html.escape(p['url'])}</id>
    <published>{p['createdAt']}</published>
    <updated>{p['createdAt']}</updated>
    <content type="html">{html.escape(bullets_to_lists(p['bodyHTML']))}</content>
  </entry>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>BEER Updates</title>
  <subtitle>Release announcements for BEER, a Mac app for playing Windows Steam games on Apple Silicon.</subtitle>
  <link href="{SITE}/{PAGE}"/>
  <link rel="self" href="{SITE}/{FEED}"/>
  <id>{SITE}/{PAGE}</id>
  <updated>{updated}</updated>
  <author><name>Coby Whittekiend</name></author>
{chr(10).join(entries)}
</feed>
"""


TAGS = re.compile(r"<[^>]+>")
LATEST = re.compile(r"(<!-- LATEST_UPDATES -->).*?(<!-- /LATEST_UPDATES -->)", re.S)
LATEST_COUNT = 3


def excerpt(body_html, limit=220):
    """First paragraph of a post as plain text, cut at a word boundary."""
    m = PARA.search(body_html)
    text = html.unescape(TAGS.sub(" ", m.group(2) if m else body_html))
    text = re.sub(r"\s+", " ", text.split("•")[0]).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def render_cards(posts):
    """Cards for the newest announcements, shown on the BEER page."""
    if not posts:
        return '<p class="empty">No announcements yet.</p>'
    cards = []
    for i, p in enumerate(posts[:LATEST_COUNT]):
        d = parse_date(p["createdAt"])
        latest = i == 0
        cards.append(f"""        <a class="update-card{' latest' if latest else ''}" href="{PAGE}#post-{p['number']}">
          <span class="card-top"><time datetime="{p['createdAt']}">{d.strftime('%B %-d, %Y')}</time>{'<span class="badge">Latest</span>' if latest else ''}</span>
          <h3>{html.escape(p['title'])}</h3>
          <p>{html.escape(excerpt(p['bodyHTML']))}</p>
          <span class="more">Read the announcement
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          </span>
        </a>""")
    return "\n".join(cards)


def fill_beer_page(posts):
    page = ROOT / "beer.html"
    s = page.read_text()
    if not LATEST.search(s):
        sys.exit("beer.html is missing the LATEST_UPDATES markers")
    s = LATEST.sub(lambda m: f"{m.group(1)}\n{render_cards(posts)}\n{m.group(2)}", s, count=1)
    page.write_text(s)


def main():
    posts = fetch()
    fill_beer_page(posts)
    body = "\n".join(render_post(p) for p in posts) if posts else \
        '<p class="empty">No announcements yet.</p>'
    page = (TEMPLATE.read_text()
            .replace("{{POST_INDEX}}", render_index(posts))
            .replace("{{POSTS}}", body)
            .replace("{{COUNT}}", str(len(posts))))
    (ROOT / PAGE).write_text(page)
    (ROOT / FEED).write_text(render_feed(posts))
    print(f"Wrote {PAGE} and {FEED} with {len(posts)} posts")


if __name__ == "__main__":
    main()
