import os
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

import structlog
from fastapi import APIRouter
from fastapi.responses import FileResponse

from wendy import agent


router = APIRouter()
log = structlog.get_logger()


@router.get(
    "/download/{id}",
    description="下载存档",
)
async def zip(id: int):
    cluster_path = agent.get_cluster_path(str(id))
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
