from typing import List

import io
import os
import zipfile

from pydantic import BaseModel
from fastapi import APIRouter, Body, Response

from wendy import steamcmd
from wendy.agent import download_mods
from wendy.settings import GAME_ARCHIVE_PATH


router = APIRouter()


class ModInfo(BaseModel):
    """模组modinfo.lua内容"""

    id: str
    code: str | bytes


@router.post(
    "/info",
    description="获取模组modinfo.lua内容",
)
async def read_modinfo(
    mods: List[str] = Body(),
) -> List[ModInfo]:
    mod_path, ugc_path = await download_mods(
        mods=mods,
        path=os.path.join(GAME_ARCHIVE_PATH, "mods"),
    )
    data = []
    code = b""
    for mod_id in mods:
        target_path = None
        path1 = os.path.join(mod_path, f"workshop-{mod_id}/modinfo.lua")
        path2 = os.path.join(ugc_path, f"content/322330/{mod_id}/modinfo.lua")
        if os.path.exists(path1):
            target_path = path1
        elif os.path.exists(path2):
            target_path = path2
        if target_path:
            with open(target_path, "rb") as file:
                code = file.read()
        data.append(ModInfo(id=mod_id, code=code.decode(errors="ignore")))
    return data


@router.post(
    "/download",
    description="下载模组",
)
async def download(
    mods: List[str] = Body(),
):
    mods_path = await download_mods(
        mods=mods,
        path=os.path.join(GAME_ARCHIVE_PATH, "mods"),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for mod_id in mods:
            dir_path = os.path.join(mods_path, mod_id)
            if os.path.isdir(dir_path):
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, mods_path)
                        zip_file.write(file_path, arcname)
            elif os.path.isfile(dir_path):
                arcname = os.path.relpath(dir_path, mods_path)
                zip_file.write(dir_path, arcname)
    buffer.seek(0)
    return Response(
        content=buffer.read(),
        headers={"Content-Disposition": "attachment; filename=mods.zip"},
        media_type="application/zip",
    )


@router.post("/publishedfiledetails")
async def publishedfiledetails(
    mods: List[str] = Body(),
):
    return await steamcmd.publishedfiledetails(mods)


@router.post("/search")
async def search(
    search_text: str = Body(),
    appid: int = Body(default=322330),
    page: int = Body(default=1),
    numperpage: int = Body(default=10),
    language: int = Body(default=6),
):
    return await steamcmd.search_mods(
        search_text,
        appid,
        page=page,
        numperpage=numperpage,
        language=language,
    )
