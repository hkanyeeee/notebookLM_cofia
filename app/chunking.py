import tiktoken
from typing import List


def chunk_text(text: str, tokens_per_chunk: int = 800, overlap_tokens: int = 80) -> List[str]:
    """
    使用 tiktoken 将文本编码为 token 后，按固定 token 数量切分为多个重叠块。

    :param text: 原始文本
    :param tokens_per_chunk: 每个 chunk 包含的 token 数，默认 800
    :param overlap_tokens: 相邻 chunk 之间重叠的 token 数，默认 80
    :return: 文本块列表
    """
    # 获取 tiktoken 的 cl100k_base 编码器（与 OpenAI GPT-4 / 3.5 默认一致）
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + tokens_per_chunk, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text_str = encoding.decode(chunk_tokens)
        chunks.append(chunk_text_str)

        # 如果已经到了文本末尾，则退出循环
        if end == len(tokens):
            break

        # 滑动窗口步长，保证 chunk 之间有重叠部分
        start += max(tokens_per_chunk - overlap_tokens, 1)

    return chunks
