from typing import List, Optional

# 统一的 Auto-Ingest 固定会话ID列表（兼容历史与当前）
AUTO_INGEST_SESSION_IDS: List[str] = [
    "fixed_session_id_for_agenttic_ingest",  # 当前端点使用
    "fixed_session_id_for_auto_ingest",      # 兼容历史数据
]


def get_known_auto_ingest_session_ids(extra: Optional[str] = None) -> List[str]:
    """返回已知的 auto-ingest 会话ID，包含可选的额外ID（置于首位）。"""
    ids: List[str] = []
    if extra and extra not in ids:
        ids.append(extra)
    for sid in AUTO_INGEST_SESSION_IDS:
        if sid not in ids:
            ids.append(sid)
    return ids


