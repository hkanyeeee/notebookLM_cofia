from urllib.parse import urlparse


def determine_parent_url(url: str) -> str:
    """
    统一的父URL归属规则：
    - lmstudio.ai/docs/*: 归属到两级路径（如 /docs/python）
    - python.langchain.com/api_reference/*: 统一归属到 /api_reference
    - 通用：保留前两级路径作为父URL（若不足两级则用自身规范化路径）
    """
    parsed = urlparse(url)
    normalized_path = parsed.path.rstrip('/')
    parts = [p for p in normalized_path.split('/') if p]

    # lmstudio 文档两级聚合
    if parsed.netloc.endswith('lmstudio.ai') and 'docs' in parts:
        if len(parts) >= 2 and parts[0] == 'docs':
            return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:2])}"

    # LangChain Python API Reference 统一聚合
    if parsed.netloc.endswith('python.langchain.com') and 'api_reference' in parts:
        return f"{parsed.scheme}://{parsed.netloc}/api_reference"

    # 通用：两级
    if len(parts) >= 2:
        return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(parts[:2])}"

    return f"{parsed.scheme}://{parsed.netloc}{normalized_path}"


