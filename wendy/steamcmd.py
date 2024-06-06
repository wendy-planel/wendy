import httpx


async def dst_version() -> str:
    """获取dst版本号"""
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.steamcmd.net/v1/info/343050")
    return response.json()["data"]["343050"]["depots"]["branches"]["public"]["buildid"]
