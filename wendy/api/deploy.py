from fastapi import APIRouter, Body, Path
from tortoise.transactions import atomic

from wendy.cluster import Cluster
from wendy import models, agent, steamcmd
from wendy.constants import DeployStatus
from wendy.settings import DEPLOYMENT_PATH


router = APIRouter()


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
    cluster = Cluster.create_from_default(
        id=str(deploy.id),
        ports=ports,
        version=version,
        cluster_token=cluster_token,
        cluster_name=cluster_name,
        cluster_description=cluster_description,
    )
    # 保存游戏存档
    cluster.save(DEPLOYMENT_PATH)
    await agent.deploy(str(deploy.id), cluster)
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
