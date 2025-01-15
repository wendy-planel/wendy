from typing import List

import json
import asyncio
import collections

import aiodocker
import structlog
from sse_starlette.sse import EventSourceResponse
from fastapi import APIRouter, Body, Query, Request

from wendy import agent, models
from wendy.cluster import Cluster, ClusterWorld


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "/{id}",
    description="控制台执行命令",
)
async def command_(
    id: int,
    command: str = Body(),
    world_index: int = Body(),
):
    command = command.strip() + "\n"
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    world = cluster.world[world_index]
    docker_api = world.docker_api
    container_name = world.container
    await agent.attach(command, docker_api, container_name)
    return "ok"


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
    "/logs/tail/{id}",
    description="获取在线日志",
)
async def tail_logs(
    id: int,
    tail: int | str = Query(default="all"),
    since: int = Query(default=0),
    until: int = Query(default=0),
    timestamps: bool = Query(default=False),
    world_index: int = Query(default=0),
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.cluster)
    world = cluster.world[world_index]
    docker_api = world.docker_api
    container_name = world.container
    tail += 1
    logs = collections.deque(maxlen=tail)
    _iter = agent.logs(
        docker_api,
        container_name,
        since,
        until,
        timestamps,
    )
    async for line in _iter:
        logs.append(line)
        if len(logs) == tail:
            logs.popleft()
    return logs


class LogFollow:
    def __init__(
        self,
        request: Request,
        since: int,
    ):
        self.request = request
        self.since = since
        self.queue = asyncio.Queue()
        self.tasks: List[asyncio.Task] = []
        self._started = False
        self._watch_task: asyncio.Task | None = None

    def __aiter__(self):
        return self

    async def read(
        self,
        key: str,
        world: ClusterWorld,
        queue: asyncio.Queue,
    ):
        async with aiodocker.Docker(world.docker_api) as docker:
            container = await docker.containers.get(world.container)
            _iter = container.log(
                stdout=True,
                stderr=True,
                follow=True,
                since=self.since,
            )
            line = ""
            async for data in _iter:
                for ch in data:
                    if ch == "\n":
                        message = {"key": key, "line": line}
                        await queue.put(json.dumps(message))
                        line = ""
                    else:
                        line += ch

    async def _watch(self):
        while True:
            if await self.request.is_disconnected():
                break
            await asyncio.sleep(5)
        await self.aclose()

    async def aclose(self):
        for task in self.tasks:
            task.cancel()

    async def __anext__(self):
        if not self._started:
            async for deploy in models.Deploy.all():
                cluster = Cluster.model_validate(deploy.cluster)
                for index, world in enumerate(cluster.world):
                    key = f"{deploy.id}_{index}"
                    task = asyncio.create_task(self.read(key, world, self.queue))
                    self.tasks.append(task)
            self._started = True
            self._watch_task = asyncio.create_task(self._watch())
        return await self.queue.get()

    async def __aexit__(self, _exc_type, _exc, _tb):
        await self.aclose()


@router.get("/logs/follow")
async def logs(request: Request, since: int = Query(default=0)):
    return EventSourceResponse(LogFollow(request, since), send_timeout=60)
