import httpx
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from datetime import datetime

from ..database import get_db
from ..models import WorkflowExecution
from ..config import get_settings

settings = get_settings()

router = APIRouter()

# n8n API 配置
N8N_BASE_URL = "http://localhost:5678/api/v1"  # 根据实际n8n部署地址调整
N8N_AUTH = None  # 如果n8n启用了认证，在这里配置

class N8nClient:
    """n8n API 客户端"""
    
    def __init__(self, base_url: str = N8N_BASE_URL, auth: Optional[Dict] = N8N_AUTH):
        self.base_url = base_url
        self.auth = auth

    async def get_executions(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """获取工作流执行列表"""
        try:
            params = {"limit": limit}
            if status:
                params["status"] = status
                
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/executions",
                    params=params,
                    auth=self.auth
                )
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"调用n8n API失败: {str(e)}")

    async def get_execution_by_id(self, execution_id: str) -> Dict[str, Any]:
        """根据执行ID获取执行详情"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/executions/{execution_id}",
                    auth=self.auth
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取执行详情失败: {str(e)}")

# 全局n8n客户端实例
n8n_client = N8nClient()

@router.post("/workflow-execution", summary="记录工作流执行")
async def create_workflow_execution(
    execution_data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    记录工作流执行信息
    
    预期数据格式:
    {
        "execution_id": "n8n执行ID",
        "document_name": "文档名称",
        "workflow_id": "工作流ID（可选）",
        "session_id": "会话ID"
    }
    """
    try:
        execution = WorkflowExecution(
            execution_id=execution_data["execution_id"],
            document_name=execution_data["document_name"],
            workflow_id=execution_data.get("workflow_id"),
            session_id=execution_data["session_id"],
            status="running"
        )
        
        db.add(execution)
        await db.commit()
        await db.refresh(execution)
        
        return {
            "success": True,
            "message": "工作流执行记录已创建",
            "execution_id": execution.execution_id
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"创建工作流执行记录失败: {str(e)}")

@router.put("/workflow-execution/{execution_id}/status", summary="更新工作流执行状态")
async def update_workflow_status(
    execution_id: str,
    status_data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    更新工作流执行状态
    
    预期数据格式:
    {
        "status": "success|error|stopped",
        "stopped_at": "结束时间（可选）"
    }
    """
    try:
        stmt = select(WorkflowExecution).where(WorkflowExecution.execution_id == execution_id)
        result = await db.execute(stmt)
        execution = result.scalar_one_or_none()
        
        if not execution:
            raise HTTPException(status_code=404, detail="找不到指定的工作流执行记录")
        
        execution.status = status_data["status"]
        if status_data.get("stopped_at"):
            execution.stopped_at = datetime.fromisoformat(status_data["stopped_at"])
        elif status_data["status"] in ["success", "error", "stopped"]:
            execution.stopped_at = datetime.utcnow()
        
        await db.commit()
        
        return {
            "success": True,
            "message": "工作流执行状态已更新",
            "execution_id": execution_id,
            "status": execution.status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"更新工作流执行状态失败: {str(e)}")

@router.get("/workflow-executions", summary="获取工作流执行列表")
async def get_workflow_executions(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """获取工作流执行列表（从数据库和n8n API）"""
    try:
        # 从数据库获取记录
        stmt = select(WorkflowExecution).order_by(desc(WorkflowExecution.created_at)).limit(limit)
        
        if session_id:
            stmt = stmt.where(WorkflowExecution.session_id == session_id)
        if status:
            stmt = stmt.where(WorkflowExecution.status == status)
            
        result = await db.execute(stmt)
        db_executions = result.scalars().all()
        
        # 从n8n API获取最新状态
        try:
            n8n_executions = await n8n_client.get_executions(status="running" if status == "running" else None)
            n8n_execution_map = {exec["id"]: exec for exec in n8n_executions}
        except:
            n8n_execution_map = {}
        
        # 合并数据库记录和n8n API数据
        combined_executions = []
        for db_exec in db_executions:
            n8n_data = n8n_execution_map.get(db_exec.execution_id, {})
            
            combined_executions.append({
                "id": db_exec.id,
                "executionId": db_exec.execution_id,
                "documentName": db_exec.document_name,
                "workflowId": db_exec.workflow_id,
                "status": n8n_data.get("status", db_exec.status),  # 优先使用n8n的最新状态
                "startedAt": db_exec.started_at.isoformat() if db_exec.started_at else None,
                "stoppedAt": db_exec.stopped_at.isoformat() if db_exec.stopped_at else None,
                "sessionId": db_exec.session_id
            })
        
        # 分离正在运行和已完成的工作流
        running_workflows = [exec for exec in combined_executions if exec["status"] == "running"]
        completed_workflows = [exec for exec in combined_executions if exec["status"] != "running"]
        
        return {
            "success": True,
            "runningWorkflows": running_workflows,
            "workflowHistory": completed_workflows,
            "total": len(combined_executions)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工作流执行列表失败: {str(e)}")

@router.get("/workflow-executions/running", summary="获取正在运行的工作流")
async def get_running_workflows(
    session_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取正在运行的工作流列表"""
    try:
        # 从n8n API获取正在运行的工作流
        n8n_running = await n8n_client.get_executions(status="running")
        
        # 从数据库获取对应的文档信息
        if n8n_running:
            execution_ids = [exec["id"] for exec in n8n_running]
            stmt = select(WorkflowExecution).where(WorkflowExecution.execution_id.in_(execution_ids))
            if session_id:
                stmt = stmt.where(WorkflowExecution.session_id == session_id)
            
            result = await db.execute(stmt)
            db_executions = result.scalars().all()
            db_exec_map = {exec.execution_id: exec for exec in db_executions}
        else:
            db_exec_map = {}
        
        # 合并数据
        running_workflows = []
        for n8n_exec in n8n_running:
            db_exec = db_exec_map.get(n8n_exec["id"])
            running_workflows.append({
                "executionId": n8n_exec["id"],
                "documentName": db_exec.document_name if db_exec else "未知文档",
                "status": n8n_exec.get("status", "running"),
                "startedAt": n8n_exec.get("startedAt", ""),
                "workflowId": n8n_exec.get("workflowId", ""),
                "sessionId": db_exec.session_id if db_exec else ""
            })
        
        return {
            "success": True,
            "data": running_workflows,
            "total": len(running_workflows)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取正在运行的工作流失败: {str(e)}")
