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

    mod_id: str
    mod_info: str


@router.post(
    "/info",
    description="获取模组modinfo.lua内容",
)
async def read_modinfo(
    mods: List[str] = Body(),
) -> List[ModInfo]:
    ugc_mods_path = await download_mods(
        id="mods",
        mods=mods,
        mount_path=os.path.join(GAME_ARCHIVE_PATH, "mods"),
    )
    data = []
    for mod_id in mods:
        mod_info_path = os.path.join(ugc_mods_path, f"{mod_id}/modinfo.lua")
        if not os.path.exists(mod_info_path):
            mod_info = ""
        else:
            with open(mod_info_path, "r") as file:
                mod_info = file.read()
        data.append(ModInfo(mod_id=mod_id, mod_info=mod_info))
    return data


@router.post(
    "/download",
    description="下载模组",
)
async def download(
    mods: List[str] = Body(),
):
    ugc_mods_path = await download_mods(
        id="mods",
        mods=mods,
        mount_path=os.path.join(GAME_ARCHIVE_PATH, "mods"),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for mod_id in mods:
            dir_path = os.path.join(ugc_mods_path, mod_id)
            if os.path.isdir(dir_path):
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ugc_mods_path)
                        zip_file.write(file_path, arcname)
            elif os.path.isfile(dir_path):
                arcname = os.path.relpath(dir_path, ugc_mods_path)
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
