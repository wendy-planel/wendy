from io import BytesIO
import tarfile
import tempfile
from typing import Literal

import os
import zipfile

import structlog
import aiodocker
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
    cluster = Cluster.create_from_default(
        id=str(deploy.id),
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
    game_mode: Literal["survival", "endless", "wilderness"] = Body(default="endless"),
    bind_ip: str = Body(default="127.0.0.1"),
    master_ip: str = Body(default="127.0.0.1"),
    vote_enabled: bool = Body(default=False),
    modoverrides: str = Body(default=modoverrides_default),
    caves_leveldataoverride: str = Body(default=caves_leveldataoverride_default),
    master_leveldataoverride: str = Body(default=master_leveldataoverride_default),
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    version = await steamcmd.dst_version()
    cluster = Cluster.create_from_default(
        id=str(id),
        bind_ip=bind_ip,
        master_ip=master_ip,
        ports=cluster.ports,
        enable_caves=enable_caves,
        docker_api=cluster.docker_api,
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
    enable_caves: bool = Body(default=True),
    docker_api: str = Body(default=DOCKER_URL_DEFAULT_DEFAULT),
):
    """上传文件部署.

    Args:
        file (UploadFile, optional): 文件.
    """
    filename = file.filename
    file_content = await file.read(1_073_741_824)
    # 切分上传文件后缀
    _, suffix = os.path.splitext(filename)
    if suffix == ".zip":
        temp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(BytesIO(file_content), "r") as zip_ref:
            zip_ref.extractall(temp_dir)
    elif suffix == ".tar":
        temp_dir = tempfile.mkdtemp()
        with tarfile.open(fileobj=BytesIO(file_content), mode="r:*") as tar_ref:
            tar_ref.extractall(temp_dir)
    else:
        raise ValueError(f"Unsupported {suffix}")
    target_file = "cluster.ini"
    upload_cluster_path = None
    for dirpath, _, filenames in os.walk(temp_dir):
        if target_file in filenames:
            # 类似  /tmp/tmpunk2y5rs/xx/xxxxxxx/Cluster_x
            upload_cluster_path = dirpath
    # 无法定位到目录
    if upload_cluster_path is None:
        raise ValueError(f"not found {target_file}")
    # 对上层目录重命名
    cluster_path = os.path.join(upload_cluster_path, os.pardir)
    os.rename(upload_cluster_path, os.path.join(cluster_path, "Cluster_1"))
    # 获取部署版本号
    version = await steamcmd.dst_version()
    deploy = await models.Deploy.create(
        content={},
        status=DeployStatus.pending.value,
    )
    # 根据ID生成7个端口号
    ports = [(10000 + deploy.id * 7 + i) for i in range(7)]
    id = str(deploy.id)
    cluster = Cluster.create_from_dir(
        id=id,
        ports=ports,
        version=version,
        cluster_path=cluster_path,
        enable_caves=enable_caves,
        docker_api=docker_api,
    )
    async with aiodocker.Docker(cluster.docker_api) as docker:
        await agent.upload_archive(
            id=id,
            cluster_path=cluster_path,
            docker=docker,
        )
    # 删除临时文件
    await agent.deploy(cluster)
    deploy.content = cluster.model_dump()
    deploy.status = DeployStatus.running.value
    await deploy.save()
    return deploy
