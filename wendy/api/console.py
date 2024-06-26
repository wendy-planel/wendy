from typing import Literal

import collections

import structlog
from fastapi import APIRouter, Body, Query

from wendy import agent, models
from wendy.cluster import Cluster


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "/command/{id}",
    description="控制台执行命令",
)
async def command(
    id: int,
    command: str = Body(),
    world: Literal["master", "caves"] = Body(),
):
    command = command.strip() + "\n"
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    world = cluster.master if world == "master" else cluster.caves
    await agent.attach(cluster.id, command, world)
    return "ok"


@router.get(
    "/logs/{id}",
    description="获取在线日志",
)
async def logs(
    id: int,
    tail: int = Query(default=50),
    world: Literal["master", "caves"] = Query(),
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    world = cluster.master if world == "master" else cluster.caves
    # 获取日志
    tail += 1
    logs = collections.deque(maxlen=tail)
    async for line in agent.logs(cluster.id, world):
        logs.append(line)
        if len(logs) == tail:
            logs.popleft()
    return logs
