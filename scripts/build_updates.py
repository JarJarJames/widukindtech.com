#!/usr/bin/env python3
"""Build beer-updates.html and beer-updates.xml from BEER's GitHub
Discussions "Announcements" category.

Needs a GitHub token in GITHUB_TOKEN (the Actions token works; locally,
`GITHUB_TOKEN=$(gh auth token) python3 scripts/build_updates.py`).
Standard library only.
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

CATEGORY_QUERY = """
query($owner: String!, $repo: String!, $slug: String!) {
  repository(owner: $owner, name: $repo) {
    discussionCategory(slug: $slug) { id }
  }
}
"""

POSTS_QUERY = """
query($owner: String!, $repo: String!, $category: ID!) {
  repository(owner: $owner, name: $repo) {
    discussions(first: 50, categoryId: $category,
                orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number title url createdAt bodyHTML
        author { login }
        comments { totalCount }
      }
    }
  }
}
"""


def graphql(query, variables):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "widukindtech-site-build"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        sys.exit(f"GraphQL errors: {data['errors']}")
    return data["data"]


def fetch():
    repo = {"owner": OWNER, "repo": REPO}
    cat = graphql(CATEGORY_QUERY, {**repo, "slug": CATEGORY_SLUG})["repository"]["discussionCategory"]
    if cat is None:
        sys.exit(f"No discussion category with slug '{CATEGORY_SLUG}'")
    nodes = graphql(POSTS_QUERY, {**repo, "category": cat["id"]})["repository"]["discussions"]["nodes"]
    return [d for d in nodes if d["author"] and d["author"]["login"] == AUTHOR]


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


def main():
    posts = fetch()
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
