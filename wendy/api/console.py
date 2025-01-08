from typing import List

import asyncio
import collections

import aiodocker
import structlog
from fastapi import APIRouter, Body, Query
from sse_starlette.sse import EventSourceResponse

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
    world_name: str = Body(),
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
async def tail_logs(
    id: int,
    tail: int = Query(default=50),
    world_name: str = Query(),
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
    tail += 1
    logs = collections.deque(maxlen=tail)
    async for line in agent.logs(docker_api, container_name):
        logs.append(line)
        if len(logs) == tail:
            logs.popleft()
    return logs


class LogFollow:
    def __init__(self):
        self._started = False
        self.queue = asyncio.Queue()
        self.tasks: List[asyncio.Task] = []

    def __aiter__(self):
        return self

    async def read(self, queue: asyncio.Queue, deploy: models.Deploy):
        cluster = Cluster.model_validate(deploy.cluster)
        for world in cluster.world:
            async with aiodocker.Docker(world.docker_api) as docker:
                container = await docker.containers.get(world.container)
                _iter = container.log(stdout=True, stderr=True, follow=True)
                async for line in _iter:
                    await queue.put(line)

    async def aclose(self):
        for task in self.tasks:
            task.cancel()

    async def __anext__(self):
        if not self._started:
            async for deploy in models.Deploy.all():
                task = asyncio.create_task(self.read(self.queue, deploy))
                self.tasks.append(task)
            self._started = True
        return await self.queue.get()


@router.get(
    "/logs",
    description="获取所有控制台日志",
)
async def sse_logs():
    return EventSourceResponse(LogFollow())
