import re
from typing import List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def is_potential_sub_doc(candidate_url: str, base_url: str) -> bool:
    """
    判断候选URL是否可能是 base_url 的子文档。
    规则（与 preview_auto_ingest 对齐）：
    - 必须与 base_url 同域名
    - 若 URL 路径是 base 路径的更深层（严格子路径），判定为子文档
    - 另外允许“同一父目录下的兄弟文档”（即与 base 同目录的其他路径）作为潜在子文档
    """
    try:
        parsed_url = urlparse(candidate_url)
        parsed_base = urlparse(base_url)

        if parsed_url.netloc != parsed_base.netloc:
            return False

        base_path = parsed_base.path.rstrip('/')
        url_path = parsed_url.path.rstrip('/')

        # 更深层严格子路径：/docs -> /docs/python
        if url_path.startswith(base_path) and len(url_path) > len(base_path):
            return True

        # 同一父目录下的兄弟文档：/docs/guide.html 与 /docs/index.html
        if base_path:
            parent_dir = base_path.rsplit('/', 1)[0] if '/' in base_path else ''
            # 允许在相同父目录下出现的其他路径
            if url_path.startswith(parent_dir):
                return True

        return False
    except Exception:
        return False


def extract_links_from_html(html: str, base_url: str) -> List[str]:
    """
    从HTML中提取潜在的子文档链接，返回绝对URL列表（去重）。
    - 提取 <a href> 链接
    - 提取 button 的 onclick 中的跳转链接
    - 过滤掉 #/javascript/mailto/tel 等无效链接
    - 只保留与 base_url 同域、可能是子文档的链接
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    seen = set()

    def add_url(href: str):
        if not href:
            return
        href = href.strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return
        abs_url = urljoin(base_url, href)
        if abs_url in seen:
            return
        if is_potential_sub_doc(abs_url, base_url):
            seen.add(abs_url)
            urls.append(abs_url)

    for a_tag in soup.find_all("a", href=True):
        add_url(a_tag.get("href"))

    for button in soup.find_all("button"):
        onclick = button.get("onclick", "") or ""
        if "location" in onclick or "href" in onclick:
            m = re.search(r"['\"]([^'\"]+)['\"]", onclick)
            if m:
                add_url(m.group(1))

    return urls


