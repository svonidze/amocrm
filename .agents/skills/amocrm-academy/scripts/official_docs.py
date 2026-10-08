"""Save public amoCRM references linked by lesson pages as Markdown snapshots."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from markdownify import markdownify

MARKER = "<!-- amocrm-academy:official-doc -->"


def canonical(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"www.amocrm.ru", "amocrm.ru"}:
        raise ValueError("Expected a public amoCRM documentation URL")
    if not parts.path.startswith(("/support/", "/developers/content/")):
        raise ValueError("URL is outside the support and developer documentation")
    if any(part in {".", ".."} for part in parts.path.split("/")):
        raise ValueError("Unsafe documentation path")
    return urlunsplit(("https", "www.amocrm.ru", parts.path.rstrip("/"), "", ""))


def destination(root, url):
    return root / "docs/amocrm" / (urlsplit(canonical(url)).path.lstrip("/") + ".md")


def extract(html, url):
    soup = BeautifulSoup(html, "html.parser")
    if urlsplit(url).path.startswith("/developers/"):
        content = soup.select_one("main .content-block__text")
        title = soup.select_one("main .content-block__title_large")
    else:
        content = soup.select_one(".content-block__faq-container")
        title = soup.select_one("h1.feature__header_main, h2.faq__section_head")
    if content is None or title is None:
        raise ValueError("Documentation content not found; login or page layout may have changed")
    # Only section article links expand the queue, never navigation or article crosslinks.
    children = [canonical(urljoin(url, a["href"]))
                for a in content.select("a.faq__item_link[href]")]
    article = content.select_one(".faq__item_content")
    if article is not None and article.get_text(strip=True):
        content = article
    for element in content.select("script, style, form, input, button, iframe"):
        element.decompose()
    for element in content.select("a[href], img[src]"):
        attr = "href" if element.name == "a" else "src"
        value = element[attr]
        if value.startswith("#"):
            element[attr] = url + value
        else:
            element[attr] = urljoin(url + "/", value)
    body = markdownify(str(content), heading_style="ATX", bullets="-", strip=["div", "span"])
    body = "\n".join(line.rstrip() for line in body.splitlines())
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) < 60:
        raise ValueError("Empty documentation body")
    return title.get_text(" ", strip=True), body, list(dict.fromkeys(children))


def save(root, url, refresh=False):
    path = destination(root, url)
    cache = root / "work/official-docs" / (hashlib.sha256(url.encode()).hexdigest() + ".html")
    if path.exists() and MARKER not in path.read_text():
        raise ValueError("Existing document is not a generated snapshot; preserve it")
    if path.exists() and not refresh:
        if cache.exists():
            title, _, children = extract(cache.read_bytes(), url)
            return title, children
        # Recover section links from the snapshot when its temporary HTML was removed.
        text = path.read_text()
        title = text.splitlines()[0].removeprefix("# ")
        prefix = url + "/"
        children = []
        if len(urlsplit(url).path.strip("/").split("/")) == 2:
            for target in re.findall(r"\]\((https://www\.amocrm\.ru/[^)]+)\)", text):
                if target.startswith(prefix):
                    children.append(canonical(target))
        return title, list(dict.fromkeys(children))
    with urlopen(Request(url, headers={"User-Agent": "amoCRM-Academy-Notes/1.0"}), timeout=30) as response:
        canonical(response.url)
        raw = response.read()
    title, body, children = extract(raw, url)
    day = datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()
    result = f"# {title}\n\n{MARKER}\n\nИсточник: [{title}]({url}).\nДата сохранения: {day}.\nФормат: текст официальной страницы, автоматически преобразованный в Markdown.\n\n{body}\n"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".md.tmp")
    temporary.write_text(result)
    temporary.replace(path)
    return title, children


def write_index(root, errors):
    start, end = "<!-- amocrm-docs:toc:start -->", "<!-- amocrm-docs:toc:end -->"
    index = root / "docs/README.md"
    previous = index.read_text() if index.exists() else "# Документация к урокам\n\n"
    rows = [start]
    for prefix, heading in [("amocrm", "amoCRM"), ("vendors", "Документация поставщиков"),
                            ("academy", "Материалы Академии")]:
        paths = sorted((root / "docs" / prefix).rglob("*.md"))
        if paths:
            rows.extend([f"## {heading}", ""])
        for path in paths:
            title = path.read_text().splitlines()[0].removeprefix("# ")
            rows.append(f"- [{title}]({path.relative_to(index.parent).as_posix()})")
        rows.append("")
    if errors:
        rows.extend(["## Недоступные источники", ""])
        rows.extend(f"- {e['url']}: {e['error']}" for e in errors)
    rows.append(end)
    block = "\n".join(rows)
    if start in previous and end in previous:
        previous = previous[:previous.index(start)] + block + previous[previous.index(end) + len(end):]
    else:
        previous += block + "\n"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="+", type=Path, help="Selected lesson page.md files")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--refresh", action="store_true", help="Explicitly refresh generated snapshots")
    args = parser.parse_args()
    root = args.root.resolve()
    seeds = {}
    for page in args.pages:
        for url in re.findall(r"\]\((https?://[^)]+)\)", page.read_text()):
            try:
                seeds.setdefault(canonical(url), []).append(str(page))
            except ValueError:
                continue
    if not seeds:
        parser.error("No official amoCRM documentation links in the selected pages")
    queue = list(seeds)
    seen = set()
    documents, errors = [], []
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            title, children = save(root, url, args.refresh)
            documents.append({"title": title, "url": url,
                              "file": str(destination(root, url).relative_to(root))})
            queue.extend(children)
            print(json.dumps({"saved": url, "articles": len(children)}, ensure_ascii=False), flush=True)
        except Exception as error:
            # Exception text may contain URLs or remote data; keep only its type here.
            errors.append({"url": url, "error": type(error).__name__})
            print(json.dumps(errors[-1]), flush=True)
    report = {"seeds": seeds, "documents": documents, "errors": errors}
    report_path = root / "work/official-docs/report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    write_index(root, errors)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
