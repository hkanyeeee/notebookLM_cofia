import re
from typing import List

def chunk_text(text: str, sentences_per_chunk: int = 7, overlap_sentences: int = 2) -> List[str]:
    """
    使用正则表达式将文本按句子分割成多个重叠的块。
    这是一个不依赖外部库的健壮实现。

    :param text: 要分块的原始文本。
    :param sentences_per_chunk: 每个块中大致包含的句子数量。
    :param overlap_sentences: 块与块之间重叠的句子数量。
    :return: 文本块的列表。
    """
    # 正则表达式，用于匹配句子结束符（.!?）以及换行符
    # Positive lookbehind `(?<=[.!?\n])` 确保分隔符本身被保留在句子末尾
    sentence_enders = re.compile(r'(?<=[.!?\n])\s+')
    sentences = sentence_enders.split(text)
    
    # 过滤掉可能产生的空字符串
    sentences = [s.strip() for s in sentences if s.strip()]
    
    chunks = []
    start_index = 0
    
    # 使用滑动窗口的方式来创建重叠的块
    while start_index < len(sentences):
        end_index = min(start_index + sentences_per_chunk, len(sentences))
        chunk = " ".join(sentences[start_index:end_index])
        chunks.append(chunk)
        
        if end_index == len(sentences):
            break
            
        start_index += (sentences_per_chunk - overlap_sentences)
        
    return chunks
