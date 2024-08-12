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
    world_name: str = Body(default="Master"),
):
    command = command.strip() + "\n"
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    container_name = docker_api = None
    for world in cluster.world:
        if world.name == world_name:
            docker_api = world.docker_api
            container_name = world.container
    if docker_api is None:
        raise ValueError(f"world {world_name} not found")
    await agent.attach(command, docker_api, container_name)
    return "ok"


@router.get(
    "/logs/{id}",
    description="获取在线日志",
)
async def logs(
    id: int,
    tail: int = Query(default=50),
    world_name: str = Query(default="Master"),
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    container_name = docker_api = None
    for world in cluster.world:
        if world.name == world_name:
            docker_api = world.docker_api
            container_name = world.container
    if docker_api is None:
        raise ValueError(f"world {world_name} not found")
    # 获取日志
    tail += 1
    logs = collections.deque(maxlen=tail)
    async for line in agent.logs(docker_api, container_name):
        logs.append(line)
        if len(logs) == tail:
            logs.popleft()
    return logs
