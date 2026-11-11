#!/usr/bin/env python3
"""抓取上海市金山区第一实验小学"多元书香"栏目指定序号区间的故事文本。

用法：
    python scrape_stories.py                # 默认抓取 6118-6215
    python scrape_stories.py 6118 6215      # 指定起止序号（含两端）
"""

import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.jsedu.sh.cn/dysx/p/{}.html"
DEFAULT_START = 6118
DEFAULT_END = 6215
OUTPUT_DIR = Path(__file__).resolve().parent / "stories"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# Windows 文件名非法字符
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
# 段落块标记（正文中不会出现的控制字符）
BLOCK_MARKER = "\x01"


def random_delay() -> None:
    """每次请求前随机等待 5-7 秒。"""
    seconds = random.uniform(5.0, 7.0)
    print(f"    等待 {seconds:.1f}s ...", flush=True)
    time.sleep(seconds)


def fetch(session: requests.Session, url: str, retries: int = 3) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            print(f"    请求失败（第 {attempt}/{retries} 次）：{exc}", flush=True)
            if attempt < retries:
                time.sleep(5 * attempt)
    return None


def extract_title(soup: BeautifulSoup, article) -> str:
    # 正文前一个 div 是作者/时间信息，再前一个 div 是标题
    author_div = article.find_previous_sibling("div")
    title_div = author_div.find_previous_sibling("div") if author_div else None
    if title_div:
        title = title_div.get_text(strip=True)
        if title:
            return title

    # 兜底：使用 <title>，去掉站点后缀
    if soup.title and soup.title.string:
        return soup.title.string.split("_")[0].strip()
    return ""


def extract_paragraphs(article) -> list[str]:
    """按原文的结构重组段落。

    正文有两种排版：<br> 硬换行 + 段首缩进，或 <p> 标签分段。
    行首无缩进的行是上一句的续行。
    """
    # 把 <p>/<li> 块转成带段落标记的文本，避免整篇被拼成一段
    for block in article.find_all(["p", "li"]):
        block.replace_with(f"\n{BLOCK_MARKER}{block.get_text(chr(10))}\n")

    raw_text = article.get_text("\n")
    raw_text = raw_text.replace("\xa0", " ").replace("\u3000", " ")

    paragraphs: list[str] = []
    current = ""

    for raw_line in raw_text.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue

        forced_break = line.lstrip().startswith(BLOCK_MARKER)
        stripped = line.strip().lstrip(BLOCK_MARKER).strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))

        # 章节标记，如 "◇  一  ◇"
        if stripped.startswith("◇") and stripped.endswith("◇"):
            if current:
                paragraphs.append(current)
                current = ""
            paragraphs.append(stripped)
            continue

        if forced_break or indent >= 2 or not current:
            if current:
                paragraphs.append(current)
            current = stripped
        else:
            current += stripped

    if current:
        paragraphs.append(current)
    return paragraphs


def safe_filename(title: str) -> str:
    name = ILLEGAL_CHARS.sub("", title).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name or "untitled"


def save_story(paragraphs: list[str], filename: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{filename}.txt"
    index = 2
    while path.exists():
        path = OUTPUT_DIR / f"{filename}_{index}.txt"
        index += 1
    path.write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
    return path


def main() -> int:
    start = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_START
    end = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_END
    if start > end:
        start, end = end, start

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    saved, skipped, failed = 0, [], []

    total = end - start + 1
    for idx, page_id in enumerate(range(start, end + 1), 1):
        url = BASE_URL.format(page_id)
        print(f"[{idx}/{total}] {url}", flush=True)

        if idx > 1:
            random_delay()

        html = fetch(session, url)
        if html is None:
            failed.append((page_id, "请求失败"))
            continue

        soup = BeautifulSoup(html, "lxml")
        article = soup.find("div", class_="article_content")
        if article is None:
            skipped.append((page_id, "无正文"))
            print("    跳过：页面没有 article_content", flush=True)
            continue

        title = extract_title(soup, article)
        paragraphs = extract_paragraphs(article)
        # 部分页面正文开头重复了标题，去掉
        if paragraphs and paragraphs[0] == title:
            paragraphs.pop(0)
        if not paragraphs:
            skipped.append((page_id, "正文为空"))
            print("    跳过：正文为空", flush=True)
            continue

        path = save_story(paragraphs, safe_filename(title))
        saved += 1
        print(f"    已保存：{path.name}（{len(paragraphs)} 段）", flush=True)

    print("\n完成：", flush=True)
    print(f"  成功 {saved} 篇", flush=True)
    if skipped:
        print(f"  跳过 {len(skipped)} 篇：{skipped}", flush=True)
    if failed:
        print(f"  失败 {len(failed)} 篇：{failed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
