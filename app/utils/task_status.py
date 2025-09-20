"""
后台任务状态管理器
用于跟踪 agentic ingest 子文档处理的进度
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"  # 部分成功状态
    FAILED = "failed"


@dataclass
class SubDocTask:
    """子文档任务信息"""
    url: str
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class IngestTaskStatus:
    """摄取任务状态"""
    task_id: str
    parent_url: str
    document_name: str
    collection_name: str
    total_sub_docs: int
    completed_sub_docs: int = 0
    failed_sub_docs: int = 0
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    sub_docs: List[SubDocTask] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.sub_docs is None:
            self.sub_docs = []
    
    @property
    def progress_percentage(self) -> float:
        """计算进度百分比"""
        if self.total_sub_docs == 0:
            return 100.0
        return (self.completed_sub_docs / self.total_sub_docs) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，便于JSON序列化"""
        result = asdict(self)
        # 转换datetime对象为字符串
        for key, value in result.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat() if value else None
        
        # 处理sub_docs中的datetime
        for sub_doc in result.get('sub_docs', []):
            for key, value in sub_doc.items():
                if isinstance(value, datetime):
                    sub_doc[key] = value.isoformat() if value else None
        
        # 🔥 修复：手动添加progress_percentage属性计算结果
        result['progress_percentage'] = self.progress_percentage
        
        return result


class IngestTaskManager:
    """摄取任务管理器"""
    
    def __init__(self):
        self.active_tasks: Dict[str, IngestTaskStatus] = {}
        self._lock = asyncio.Lock()
    
    async def create_task(
        self,
        task_id: str,
        parent_url: str,
        document_name: str,
        collection_name: str,
        sub_doc_urls: List[str]
    ) -> IngestTaskStatus:
        """创建新的摄取任务"""
        async with self._lock:
            sub_docs = [SubDocTask(url=url) for url in sub_doc_urls]
            
            task = IngestTaskStatus(
                task_id=task_id,
                parent_url=parent_url,
                document_name=document_name,
                collection_name=collection_name,
                total_sub_docs=len(sub_doc_urls),
                sub_docs=sub_docs
            )
            
            self.active_tasks[task_id] = task
            print(f"[任务管理器] 创建任务 {task_id}，包含 {len(sub_doc_urls)} 个子文档")
            return task
    
    async def start_task(self, task_id: str) -> bool:
        """开始任务"""
        async with self._lock:
            if task_id not in self.active_tasks:
                return False
            
            task = self.active_tasks[task_id]
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            
            print(f"[任务管理器] 任务 {task_id} 开始执行")
            return True
    
    async def update_sub_doc_status(
        self,
        task_id: str,
        sub_doc_url: str,
        status: TaskStatus,
        error: Optional[str] = None
    ) -> bool:
        """更新子文档状态"""
        async with self._lock:
            if task_id not in self.active_tasks:
                return False
            
            task = self.active_tasks[task_id]
            
            # 查找对应的子文档
            for sub_doc in task.sub_docs:
                if sub_doc.url == sub_doc_url:
                    old_status = sub_doc.status
                    sub_doc.status = status
                    sub_doc.error = error
                    
                    if status == TaskStatus.RUNNING and old_status == TaskStatus.PENDING:
                        sub_doc.started_at = datetime.now()
                    elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                        sub_doc.completed_at = datetime.now()
                    
                    # 更新任务统计
                    if status == TaskStatus.COMPLETED and old_status != TaskStatus.COMPLETED:
                        task.completed_sub_docs += 1
                    elif status == TaskStatus.FAILED and old_status != TaskStatus.FAILED:
                        task.failed_sub_docs += 1
                    
                    print(f"[任务管理器] 任务 {task_id} 子文档 {sub_doc_url} 状态更新为 {status}")
                    
                    # 检查是否所有子文档都完成了
                    await self._check_task_completion(task_id)
                    return True
            
            return False
    
    async def _check_task_completion(self, task_id: str):
        """检查任务是否完成"""
        if task_id not in self.active_tasks:
            return
        
        task = self.active_tasks[task_id]
        
        # 如果所有子文档都处理完成（成功或失败）
        if task.completed_sub_docs + task.failed_sub_docs >= task.total_sub_docs:
            task.completed_at = datetime.now()
            
            if task.failed_sub_docs == 0:
                # 全部成功
                task.status = TaskStatus.COMPLETED
                print(f"[任务管理器] 任务 {task_id} 全部成功完成")
            elif task.completed_sub_docs > 0:
                # 部分成功 - 有成功的也有失败的
                task.status = TaskStatus.PARTIALLY_COMPLETED
                task.error = f"成功处理 {task.completed_sub_docs} 个，失败 {task.failed_sub_docs} 个子文档"
                print(f"[任务管理器] 任务 {task_id} 部分成功完成：{task.error}")
            else:
                # 全部失败
                task.status = TaskStatus.FAILED
                task.error = f"所有 {task.failed_sub_docs} 个子文档处理失败"
                print(f"[任务管理器] 任务 {task_id} 全部失败：{task.error}")
    
    async def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        async with self._lock:
            if task_id not in self.active_tasks:
                return
            
            task = self.active_tasks[task_id]
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now()
            
            print(f"[任务管理器] 任务 {task_id} 失败：{error}")
    
    async def get_task_status(self, task_id: str) -> Optional[IngestTaskStatus]:
        """获取任务状态"""
        async with self._lock:
            return self.active_tasks.get(task_id)
    
    async def remove_task(self, task_id: str) -> bool:
        """移除任务（通常在任务完成后清理）"""
        async with self._lock:
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
                print(f"[任务管理器] 任务 {task_id} 已清理")
                return True
            return False
    
    async def list_active_tasks(self) -> List[IngestTaskStatus]:
        """列出所有活跃任务"""
        async with self._lock:
            return list(self.active_tasks.values())
    
    async def cleanup_completed_tasks(self, max_age_hours: int = 24):
        """清理完成的任务（避免内存泄漏）"""
        async with self._lock:
            now = datetime.now()
            to_remove = []
            
            for task_id, task in self.active_tasks.items():
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    if task.completed_at:
                        age_hours = (now - task.completed_at).total_seconds() / 3600
                        if age_hours > max_age_hours:
                            to_remove.append(task_id)
            
            for task_id in to_remove:
                del self.active_tasks[task_id]
                print(f"[任务管理器] 清理过期任务 {task_id}")


# 全局任务管理器实例
ingest_task_manager = IngestTaskManager()
