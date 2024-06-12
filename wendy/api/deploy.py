import os
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

import structlog
from tortoise.transactions import atomic
from fastapi import APIRouter, Body, Path
from fastapi.responses import FileResponse

from wendy.cluster import Cluster
from wendy.constants import DeployStatus
from wendy import models, agent, steamcmd


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
    cluster_description: str = Body(),
):
    # 获取部署版本号
    version = await steamcmd.dst_version()
    deploy = await models.Deploy.create(
        content={},
        status=DeployStatus.pending,
    )
    # 根据ID生成7个端口号
    ports = [(10000 + deploy.id * 7 + i) for i in range(7)]
    id = str(deploy.id)
    cluster = Cluster.create_from_default(
        id=id,
        ports=ports,
        version=version,
        cluster_token=cluster_token,
        cluster_name=cluster_name,
        cluster_description=cluster_description,
    )
    # 保存游戏存档
    cluster_path = agent.get_cluster_path(id)
    cluster.save(cluster_path)
    await agent.deploy(id, cluster)
    # 更新状态
    deploy.content = cluster.model_dump()
    deploy.status = DeployStatus.running
    await deploy.save()
    return deploy


@router.get(
    "",
    description="获取所有部署",
)
async def reads():
    return await models.Deploy.all()


@router.delete(
    "/{id}",
    description="删除部署",
)
async def remove(
    id: int = Path,
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.delete(cluster)
    return await models.Deploy.filter(id=id).delete()


@router.delete(
    "/stop/{id}",
    description="停止",
)
async def stop(
    id: int = Path,
):
    deploy = await models.Deploy.get(id=id)
    cluster = Cluster.model_validate(deploy.content)
    await agent.stop(cluster)
    return await models.Deploy.filter(id=id).update(status=DeployStatus.stop)


@router.get(
    "/zip/cluster/{id}",
    description="下载存档",
)
async def zip(
    id: str = Path,
):
    cluster_path = agent.get_cluster_path(id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_zip_file:
        zip_path = temp_zip_file.name
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
        for root, _, files in os.walk(cluster_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, cluster_path)
                try:
                    zip_file.write(file_path, arcname)
                except Exception as e:
                    log.exception(f"zip cluster {id} error: {e}")
    return FileResponse(zip_path, filename="cluster.zip")
