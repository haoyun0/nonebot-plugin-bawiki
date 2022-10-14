import asyncio
import re
import time
from datetime import datetime
from io import BytesIO
from typing import List

from aiohttp import ClientSession
from nonebot import logger
from nonebot_plugin_htmlrender import get_new_page
from nonebot_plugin_imageutils import BuildImage, text2image
from playwright.async_api import Page

from .const import EXTRA_L2D_LI, RES_CALENDER_BANNER
from .util import parse_time_delta


async def game_kee_request(url, **kwargs):
    async with ClientSession() as s:
        async with s.get(
            url, headers={"game-id": "0", "game-alias": "ba"}, **kwargs
        ) as r:
            ret = await r.json()
            if ret["code"] != 0:
                raise ConnectionError(ret["msg"])
            return ret["data"]


async def get_calender():
    ret = await game_kee_request("https://ba.gamekee.com/v1/wiki/index")

    for i in ret:
        if i["module"]["id"] == 12:
            li: list = i["list"]

            now = time.time()
            li = [x for x in li if (now < x["end_at"])]

            li.sort(key=lambda x: x["end_at"])
            li.sort(key=lambda x: x["importance"], reverse=True)
            return li


async def get_stu_li():
    ret = await game_kee_request("https://ba.gamekee.com/v1/wiki/entry")

    for i in ret["entry_list"]:
        if i["id"] == 23941:

            for ii in i["child"]:
                if ii["id"] == 49443:
                    return {x["name"]: x for x in ii["child"]}


async def get_stu_cid_li():
    return {x: y["content_id"] for x, y in (await get_stu_li()).items()}


def game_kee_page_url(sid):
    return f"https://ba.gamekee.com/{sid}.html"


async def get_game_kee_page(url):
    async with get_new_page() as page:  # type:Page
        await page.goto(url, timeout=60 * 1000)

        # 删掉header
        await page.add_script_tag(
            content='document.getElementsByClassName("wiki-header")'
            ".forEach((v)=>{v.remove()})"
        )

        # 展开折叠的语音
        folds = await page.query_selector_all('xpath=//div[@class="fold-table-btn"]')
        for i in folds:
            try:
                await i.click()
            except:
                pass

        return await (
            await page.query_selector('xpath=//div[@class="wiki-detail-body"]')
        ).screenshot()


async def get_calender_page(ret):
    now = datetime.now()

    async def draw(it: dict):
        _p = None
        if _p := it.get("picture"):
            try:
                async with ClientSession() as _s:
                    async with _s.get(f"https:{_p}") as _r:
                        _p = await _r.read()
                _p = BuildImage.open(BytesIO(_p)).resize_width(1290).circle_corner(15)
            except:
                logger.exception("下载日程表图片失败")

        begin = datetime.fromtimestamp(it["begin_at"])
        end = datetime.fromtimestamp(it["end_at"])
        started = begin <= now
        time_remain = (end if started else begin) - now
        dd, hh, mm, ss = parse_time_delta(time_remain)

        title_p = text2image(
            f'[b]{it["title"]}[/b]', "#ffffff00", max_width=1290, fontsize=65
        )
        time_p = text2image(
            f"{begin} ~ {end}", "#ffffff00", max_width=1290, fontsize=40
        )
        desc_p = (
            text2image(
                desc.replace("<br>", ""),
                "#ffffff00",
                max_width=1290,
                fontsize=40,
            )
            if (desc := it["description"])
            else None
        )
        remain_p = text2image(
            f"剩余 [color=#fc6475]{dd}[/color] 天 [color=#fc6475]{hh}[/color] 时 "
            f"[color=#fc6475]{mm}[/color] 分 [color=#fc6475]{ss}[/color] 秒"
            f'{"结束" if started else "开始"}',
            "#ffffff00",
            max_width=1290,
            fontsize=50,
        )

        h = (
            100
            + (title_p.height + 25)
            + (time_p.height + 25)
            + (_p.height + 25 if _p else 0)
            + (desc_p.height + 25 if desc_p else 0)
            + remain_p.height
        )
        img = BuildImage.new("RGBA", (1400, h), (255, 255, 255, 70)).draw_rectangle(
            (0, 0, 10, h), "#fc6475" if it["importance"] else "#4acf75"
        )

        if not started:
            img.draw_rectangle((1250, 0, 1400, 60), "gray")
            img.draw_text((1250, 0, 1400, 60), "未开始", 50, fill="white")

        ii = 50
        img.paste(title_p, (60, ii), True)
        ii += title_p.height + 25
        img.paste(time_p, (60, ii), True)
        ii += time_p.height + 25
        if _p:
            img.paste(_p, (60, ii), True)
            ii += _p.height + 25
        if desc_p:
            img.paste(desc_p, (60, ii), True)
            ii += desc_p.height + 25
        img.paste(remain_p, (60, ii), True)
        # img = img.circle_corner(15)

        return img

    pics: List[BuildImage] = await asyncio.gather(  # type: ignore
        *[draw(x) for x in ret]
    )
    bg = (
        BuildImage.new("RGBA", (1500, 200 + sum([x.height + 50 for x in pics])))
        .gradient_color((138, 213, 244), (251, 226, 229))
        .paste(BuildImage.open(RES_CALENDER_BANNER).resize((1500, 150)))
        .draw_text(
            (50, 0, 1480, 150),
            "活动日程",
            100,
            weight="bold",
            fill="#ffffff",
            halign="left",
        )
    )

    index = 200
    for p in pics:
        bg.paste(p, (50, index), True)
        index += p.height + 50

    return bg.save_jpg()


async def grab_l2d(cid):
    r: dict = await game_kee_request(f"https://ba.gamekee.com/v1/content/detail/{cid}")
    r: str = r["content"]

    i = r.find('<div class="input-wrapper">官方介绍</div>')
    i = r.find('class="slide-item" data-index="2"', i)
    ii = r.find('data-index="3"', i)

    r: str = r[i:ii]

    img = re.findall('data-real="([^"]*)"', r)

    return [f"https:{x}" for x in img]


async def get_l2d(stu_name):
    if r := EXTRA_L2D_LI.get(stu_name):
        return r

    return await grab_l2d((await get_stu_cid_li()).get(stu_name))
