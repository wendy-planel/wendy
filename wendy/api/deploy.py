from typing import List, Literal

import structlog
from tortoise.transactions import atomic
from fastapi import APIRouter, Body, File, UploadFile

from wendy.cluster import Cluster
from wendy import models, agent, steamcmd
from wendy.settings import DOCKER_URL_DEFAULT_DEFAULT
from wendy.constants import (
    DeployStatus,
    modoverrides_default,
    caves_leveldataoverride_default,
    master_leveldataoverride_default,
)


router = APIRouter()
log = structlog.get_logger()


@router.post(
    "",
    description="部署并启动",
)
@atomic(connection_name="default")
async def create(
    cluster_token: str = Body(),
    cluster_name: str = Body(),
    max_players: int = Body(default=6),
    cluster_description: str = Body(),
    cluster_password: str = Body(default=""),
    enable_caves: bool = Body(default=True),
    docker_api: str = Body(default=DOCKER_URL_DEFAULT_DEFAULT),
    game_mode: Literal["survival", "endless", "wilderness"] = Body(default="endless"),
    bind_ip: str = Body(default="127.0.0.1"),
    master_ip: str = Body(default="127.0.0.1"),
    vote_enabled: bool = Body(default=False),
    modoverrides: str = Body(default=modoverrides_default),
    caves_leveldataoverride: str = Body(default=caves_leveldataoverride_default),
    master_leveldataoverride: str = Body(default=master_leveldataoverride_default),
):
    # 获取部署版本号
    version = await steamcmd.dst_version()
    deploy = await models.Deploy.create(
        content={},
        status=DeployStatus.pending.value,
    )
    # 根据ID生成7个端口号
    ports = [(10000 + deploy.id * 7 + i) for i in range(7)]
    id = str(deploy.id)
    cluster = Cluster.create_from_default(
        id=id,
        bind_ip=bind_ip,
        master_ip=master_ip,
        ports=ports,
        enable_caves=enable_caves,
        docker_api=docker_api,
        version=version,
        game_mode=game_mode,
        max_players=max_players,
        cluster_password=cluster_password,
        cluster_token=cluster_token,
        cluster_name=cluster_name,
        cluster_description=cluster_description,
        vote_enabled=vote_enabled,
        modoverrides=modoverrides,
        caves_leveldataoverride=caves_leveldataoverride,
        master_leveldataoverride=master_leveldataoverride,
    )
    await agent.deploy(cluster)
    deploy.content = cluster.model_dump()
    deploy.status = DeployStatus.running.value
    await deploy.save()
    return deploy


@router.put(
    "/{id}",
    description="更新配置并部署",
)
async def update(
    id: int,
    cluster_token: str = Body(),
    cluster_name: str = Body(),
    max_players: int = Body(default=6),
    cluster_description: str = Body(),
    cluster_password: str = Body(default=""),
    enable_caves: bool = Body(default=True),
    docker_api: str = Body(default=DOCKER_URL_DEFAULT_DEFAULT),
    ports: List[int] = Body(default=[]),
    game_mode: Literal["survival", "endless", "wilderness"] = Body(default="endless"),
    bind_ip: str = Body(default="127.0.0.1"),
    master_ip: str = Body(default="127.0.0.1"),
    vote_enabled: bool = Body(default=False),
    modoverrides: str = Body(default=modoverrides_default),
    caves_leveldataoverride: str = Body(default=caves_leveldataoverride_default),
    master_leveldataoverride: str = Body(default=master_leveldataoverride_default),
):
    deploy = await models.Deploy.get(id=id)
    version = await steamcmd.dst_version()
    if not ports:
        ports = [(10000 + deploy.id * 7 + i) for i in range(7)]
    cluster = Cluster.create_from_default(
        id=str(id),
        bind_ip=bind_ip,
        master_ip=master_ip,
        ports=ports,
        enable_caves=enable_caves,
        docker_api=docker_api,
        version=version,
        game_mode=game_mode,
        max_players=max_players,
        cluster_password=cluster_password,
        cluster_token=cluster_token,
        cluster_name=cluster_name,
        cluster_description=cluster_description,
        vote_enabled=vote_enabled,
        modoverrides=modoverrides,
        caves_leveldataoverride=caves_leveldataoverride,
        master_leveldataoverride=master_leveldataoverride,
    )
    await agent.deploy(cluster)
    deploy.content = cluster.model_dump()
    deploy.status = DeployStatus.running.value
    await deploy.save()
    return deploy


@router.get(
    "",
    description="获取所有部署",
)
async def reads(
    status: DeployStatus,
):
    return await models.Deploy.filter(status=status.value).all()


@router.get(
    "/{id}",
    description="获取部署",
)
async def read(id: int):
    return await models.Deploy.get(id=id)


@router.delete(
    "/{id}",
    description="删除部署",
)
async def remove(id: int):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.delete(cluster)
    return await models.Deploy.filter(id=id).delete()


@router.get(
    "/stop/{id}",
    description="停止",
)
async def stop(id: int):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.stop(cluster)
    return await models.Deploy.filter(id=id).update(status=DeployStatus.stop.value)


@router.get(
    "/restart/{id}",
    description="重启",
)
async def restart(id: int):
    deploy = await models.Deploy.get(id=id)
    version = await steamcmd.dst_version()
    cluster = Cluster.model_validate(deploy.content)
    cluster.version = version
    await agent.deploy(cluster)
    deploy.content = cluster.model_dump()
    deploy.status = DeployStatus.running.value
    await deploy.save()
    return "ok"


@router.post("/upload", description="上传部署")
async def upload(
    file: UploadFile = File(),
):
    """上传文件部署.

    Args:
        file (UploadFile, optional): 文件.
    """
    pass
