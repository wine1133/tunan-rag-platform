"""批量评测接口。"""

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from common.auth import require_admin
from common.result import Result
from models import User
from service import eval_task_service

router = APIRouter(prefix="/evalTask")


class StartPayload(BaseModel):
    dataset_id: int
    # 用哪套检索策略评测，不传时用默认策略
    strategy_id: int | None = None
    # 被评测的生成 Prompt，换一个模板再跑一次就能对比 Prompt 的效果
    prompt_code: str = "RAG_ANSWER"


@router.post("/start")
async def start(
    payload: StartPayload,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
):
    """触发一次批量评测。接口只建任务就返回，真正的评测在后台跑。"""
    task_id, context = await eval_task_service.start(
        payload.dataset_id, payload.strategy_id, current_user.id, payload.prompt_code
    )
    background_tasks.add_task(eval_task_service.run, task_id, context)
    return Result.success("已开始评测，稍后刷新查看结果")


@router.get("/selectPage")
async def select_page(
    dataset_id: int | None = None,
    page_num: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
):
    """评测任务列表。"""
    return Result.success(await eval_task_service.select_tasks(dataset_id, page_num, page_size))


@router.delete("/delete/{task_id}")
async def delete(task_id: int, _: User = Depends(require_admin)):
    """删除一次评测任务，连同用例结果和报告一起删。"""
    await eval_task_service.delete(task_id)
    return Result.success()


@router.get("/results/{task_id}")
async def results(task_id: int, _: User = Depends(require_admin)):
    """一次评测的详细结果和汇总报告。"""
    return Result.success(await eval_task_service.select_results(task_id))
