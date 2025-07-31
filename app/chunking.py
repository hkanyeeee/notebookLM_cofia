from typing import List


def chunk_text(text: str, max_words: int = 500, overlap: int = 50) -> List[str]:
    """将文本按词分割为多个重叠块，以便后续向量化。"""
    words = text.split()
    chunks: List[str] = []
    start = 0
    total = len(words)
    while start < total:
        end = min(start + max_words, total)
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == total:
            break
        # 向后滑动以创建重叠
        start = max(end - overlap, end)
    return chunks