import asyncio
import json
import random
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Tuple, TypedDict

import aiofiles
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_imageutils import BuildImage

from .const import DATA_PATH, RES_PATH
from .data_bawiki import db_get_gacha_data
from .data_schaledb import (
    find_current_event,
    schale_get,
    schale_get_common,
    schale_get_stu_dict,
)
from .util import split_list

IMG_GACHA_BG = BuildImage.open(RES_PATH / "gacha_bg.png")
IMG_GACHA_CARD_BG = BuildImage.open(RES_PATH / "gacha_card_bg.png")
IMG_GACHA_CARD_MASK = BuildImage.open(RES_PATH / "gacha_card_mask.png").convert("RGBA")
IMG_GACHA_NEW = BuildImage.open(RES_PATH / "gacha_new.png")
IMG_GACHA_PICKUP = BuildImage.open(RES_PATH / "gacha_pickup.png")
IMG_GACHA_STAR = BuildImage.open(RES_PATH / "gacha_star.png")
IMG_GACHA_STU_ERR = BuildImage.open(RES_PATH / "gacha_stu_err.png")

GACHA_DATA_PATH = DATA_PATH / "gacha.json"
if not GACHA_DATA_PATH.exists():
    GACHA_DATA_PATH.write_text("{}")


class GachaData(TypedDict):
    collected: List[int]
    total_count: int


DEFAULT_GACHA_DATA: GachaData = {"collected": [], "total_count": 0}


@dataclass()
class GachaStudent:
    id: int
    new: bool = False
    pickup: bool = False


async def set_gacha_data(qq: str, data: GachaData):
    async with aiofiles.open(str(GACHA_DATA_PATH), "r+", encoding="u8") as f:
        j = json.loads(await f.read())
        j[qq] = data

        await f.seek(0)
        await f.truncate()

        await f.write(json.dumps(j))


async def get_gacha_data(qq: str) -> GachaData:
    async with aiofiles.open(str(GACHA_DATA_PATH), encoding="u8") as f:
        j = await f.read()

    data: Dict[str, GachaData] = json.loads(j)
    if not (user_data := data.get(qq)):
        user_data = DEFAULT_GACHA_DATA.copy()
        await set_gacha_data(qq, user_data)

    return user_data


async def gen_stu_img(students: Iterable[GachaStudent]) -> Tuple[BuildImage]:
    stu_li = await schale_get_stu_dict("Id")

    async def gen_single(s: GachaStudent) -> BuildImage:
        bg = IMG_GACHA_CARD_BG.copy()

        try:
            stu_j = stu_li[s.id]
            stu_star: int = stu_j["StarGrade"]
            stu_img = await schale_get(
                f"images/student/collection/Student_Portrait_{stu_j['DevName']}_Collection.webp",
                True,
            )
            stu_img = BuildImage.open(BytesIO(stu_img))
        except:
            logger.exception(f"学生数据获取失败 {s.id}")
            stu_img = IMG_GACHA_STU_ERR
            stu_star = 0

        card_img = BuildImage.new("RGBA", IMG_GACHA_CARD_MASK.size, (0, 0, 0, 0))
        card_img.image.paste(
            stu_img.resize(IMG_GACHA_CARD_MASK.size, keep_ratio=True).image,
            mask=IMG_GACHA_CARD_MASK.image,
        )

        bg = bg.paste(card_img, (26, 13), True)

        star_x_offset = int(26 + (159 - 30 * stu_star) / 2)
        star_y_offset = 198
        for i in range(stu_star):
            bg = bg.paste(IMG_GACHA_STAR, (star_x_offset + i * 30, star_y_offset), True)

        font_x_offset = 45
        font_y_offset = 2

        if s.new:
            bg = bg.paste(IMG_GACHA_NEW, (font_x_offset, font_y_offset), True)
            font_x_offset -= 2
            font_y_offset += 29

        if s.pickup:
            font_x_offset -= 4
            font_y_offset -= 4
            bg = bg.paste(IMG_GACHA_PICKUP, (font_x_offset, font_y_offset), True)

        return bg

    return await asyncio.gather(*[gen_single(x) for x in students])  # noqa


async def gen_gacha_img(
    students: Iterable[GachaStudent], count: int
) -> Optional[BytesIO]:
    line_limit = 5
    stu_cards = split_list(await gen_stu_img(students), line_limit)
    if not stu_cards:
        return
    card_w, card_h = stu_cards[0][0].size

    bg = IMG_GACHA_BG.copy()

    x_gap = 10
    y_gap = 80
    y_offset = int((bg.height - (len(stu_cards) * (y_gap + card_h) - y_gap)) / 2)
    for line in stu_cards:
        x_offset = int((bg.width - (len(line) * (x_gap + card_w) - x_gap)) / 2)
        for card in line:
            bg = bg.paste(card, (x_offset, y_offset), True)
            x_offset += card_w + x_gap
        y_offset += card_h + y_gap

    bg = bg.draw_text(
        (1678, 841, 1888, 885), "距上个3★UP", 30, weight="bold", fill=(36, 90, 126)
    ).draw_text(
        (1643, 885, 1890, 935), str(count), 30, weight="bold", fill=(255, 255, 255)
    )

    return bg.save("PNG")


async def gacha(qq: str, times: int, server: int = 0):
    common = await schale_get_common()
    c_gacha = common["regions"][server]["current_gacha"]
    if not (ev := find_current_event(c_gacha)):
        return "当前服务器没有正在进行的卡池"
    chars = ev[0]["characters"]

    stu_li = await schale_get_stu_dict("Id")
    up_3_li, up_2_li = [
        [x for x in chars if x in stu_li and stu_li[x]["StarGrade"] == y]
        for y in [3, 2]
    ]
    gacha_data = await db_get_gacha_data()

    star_3_base, star_2_base, star_1_base = [
        gacha_data["base"][x] for x in ["3", "2", "1"]
    ]
    star_3_chance, star_2_chance, star_1_chance = [
        x["chance"] for x in [star_3_base, star_2_base, star_1_base]
    ]

    up_3_chance = 0
    up_2_chance = 0
    if up_3_li:
        up_3_chance = gacha_data["up"]["3"]["chance"]
        star_3_chance -= up_3_chance
    if up_2_li:
        up_2_chance = gacha_data["up"]["2"]["chance"]
        star_2_chance -= up_2_chance

    gacha_data = await get_gacha_data(qq)
    gacha_result: List[GachaStudent] = []
    for i in range(1, times + 1):
        pool_and_weight = [
            (up_3_li, up_3_chance),
            (up_2_li, up_2_chance),
            (star_3_base["char"], star_3_chance),
            (star_2_base["char"], star_2_chance),
        ]
        if not i % 10 == 0:
            pool_and_weight.append((star_1_base["char"], star_1_chance))

        pool_and_weight = [x for x in pool_and_weight if x[0]]
        pool = [x[0] for x in pool_and_weight]
        weight = [x[1] for x in pool_and_weight]

        random.seed()
        char = random.choice(random.choices(pool, weights=weight, k=1)[0])

        is_3star_pickup = char in up_3_li
        is_pickup = is_3star_pickup or char in up_2_li
        is_new = char not in gacha_data["collected"]
        gacha_result.append(GachaStudent(id=char, pickup=is_pickup, new=is_new))

        if is_new:
            gacha_data["collected"].append(char)

        if is_3star_pickup:
            gacha_data["total_count"] = 0
        else:
            gacha_data["total_count"] += 1

    await set_gacha_data(qq, gacha_data)
    return MessageSegment.image(
        await gen_gacha_img(gacha_result, gacha_data["total_count"])
    )
