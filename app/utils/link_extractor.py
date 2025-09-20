import re
from typing import List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def is_potential_sub_doc(candidate_url: str, base_url: str) -> bool:
    """
    判断候选URL是否可能是 base_url 的子文档。
    规则：同域名，且路径为更深层或同层内的子路径。
    """
    try:
        parsed_url = urlparse(candidate_url)
        parsed_base = urlparse(base_url)

        if parsed_url.netloc != parsed_base.netloc:
            return False

        base_path = parsed_base.path.rstrip('/')
        url_path = parsed_url.path.rstrip('/')

        # 仅允许更深层路径（严格子路径）。
        # 例如 base: /docs/python 只允许 /docs/python/*，排除 /docs/python3、/docs/typescript 等兄弟文档。
        if url_path.startswith(base_path + '/'):
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


