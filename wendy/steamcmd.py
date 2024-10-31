from typing import List, Dict

import httpx


async def dst_version() -> str:
    """获取dst版本号.

    Returns:
        str: dst版本号
    """
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.steamcmd.net/v1/info/343050")
    return response.json()["data"]["343050"]["depots"]["branches"]["public"]["buildid"]


async def mods_last_updated(mods: List[str]) -> Dict[str, int]:
    """接口获取模组最后一次更新时间.

    Args:
        mods (List[str]): 模组列表.

    Returns:
        Dict[str, int]: {"模组ID": "最后一次更新时间"}.
    """
    async with httpx.AsyncClient() as client:
        url = "http://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
        post_data = {"itemcount": len(mods)}
        for i, mod_id in enumerate(mods):
            post_data[f"publishedfileids[{i}]"] = mod_id
        response = await client.post(url, data=post_data)
    # 解析数据
    data = {}
    for mod_info in response.json()["response"]["publishedfiledetails"]:
        data[mod_info["publishedfileid"]] = mod_info["time_updated"]
    return data


def parse_mods_last_updated(acf_file_path: str) -> Dict[str, int]:
    """解析acf文件获取模组最后一次更新时间.

    Args:
        acf_file_path (str): acf文件.

    Returns:
        Dict[str, int]: {"模组ID": "最后一次更新时间"}.
    """
    with open(acf_file_path, "r") as file:
        file_content = file.read()
    lines = file_content.splitlines()
    stack = [{}]
    current_key = None
    for line in lines:
        line = line.strip()
        if line == "{":
            new_dict = {}
            stack[-1][current_key] = new_dict
            stack.append(new_dict)
        elif line == "}":
            stack.pop()
        else:
            parts = line.split("\t")
            parts = [p.strip('"') for p in parts if p]
            if len(parts) == 2:
                key, value = parts[0], parts[1]
            elif len(parts) == 1:
                key, value = parts[0], None
            else:
                key, value = None, None
            if value is not None:
                stack[-1][key] = value
            else:
                current_key = key
    acf = stack[0]
    data = {}
    for mod_id, mod_info in acf["AppWorkshop"]["WorkshopItemsInstalled"].items():
        data[mod_id] = mod_info["timeupdated"]
    return data
