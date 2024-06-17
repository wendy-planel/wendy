from typing import Literal

import structlog
from fastapi import APIRouter, Body

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
