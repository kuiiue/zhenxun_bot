import time
import uuid
from datetime import datetime, timedelta
from typing import List

from apscheduler.jobstores.base import JobLookupError
from nonebot.adapters import Bot
from nonebot.exception import ActionFailed
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from nonebot_plugin_alconna import Alconna, Args, Arparma
from nonebot_plugin_alconna import At as alcAt
from nonebot_plugin_alconna import Match, Option, on_alconna
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_saa import Image, Mention, MessageFactory, Text
from nonebot_plugin_session import EventSession

from zhenxun.configs.config import NICKNAME
from zhenxun.configs.utils import PluginCdBlock, PluginExtraData, RegisterConfig
from zhenxun.services.log import logger
from zhenxun.utils.depends import GetConfig, UserName
from zhenxun.utils.platform import PlatformUtils
from zhenxun.utils.rules import ensure_group

from .config import FESTIVE_KEY, FestiveRedBagManage
from .data_source import RedBagManager

__plugin_meta__ = PluginMetadata(
    name="金币红包",
    description="运气项目又来了",
    usage="""
    塞红包 [金币数] ?[红包数=5] ?[at指定人]: 塞入红包
    开/抢: 打开红包
    退回红包: 退回未开完的红包，必须在一分钟后使用

    * 不同群组同一个节日红包用户只能开一次

    示例: 
        塞红包 1000
        塞红包 1000 10
    """.strip(),
    extra=PluginExtraData(
        author="HibiKier",
        version="0.1",
        superuser_help="""
        节日红包 [金额] [红包数] ?[指定主题文字] ? -g [群id]

        * 不同群组同一个节日红包用户只能开一次

        示例:
            节日红包 10000 20 今日出道贺金
            节日红包 10000 20 明日出道贺金 -g 123123123

        """,
        configs=[
            RegisterConfig(
                key="DEFAULT_TIMEOUT",
                value=600,
                help="普通红包默认超时时间",
                default_value=600,
                type=int,
            ),
            RegisterConfig(
                key="DEFAULT_INTERVAL",
                value=60,
                help="用户发送普通红包最小间隔时间",
                default_value=60,
                type=int,
            ),
            RegisterConfig(
                key="RANK_NUM",
                value=10,
                help="结算排行显示前N位",
                default_value=10,
                type=int,
            ),
        ],
        limits=[PluginCdBlock(result="急什么急什么，待会再发！")],
    ).dict(),
)


# def rule(session: EventSession) -> bool:
#     if gid := session.id3 or session.id2:
#         if group_red_bag := RedBagManager.get_group_data(gid):
#             return group_red_bag.check_open(gid)
#     return False


# async def rule_group(session: EventSession):
#     return rule(session) and ensure_group(session)


_red_bag_matcher = on_alconna(
    Alconna("塞红包", Args["amount", int]["num", int, 5]["user?", alcAt]),
    aliases={"金币红包"},
    priority=5,
    block=True,
    rule=ensure_group,
)

_open_matcher = on_alconna(
    Alconna("开"),
    aliases={"抢", "开红包", "抢红包"},
    priority=5,
    block=True,
    rule=ensure_group,
)

_return_matcher = on_alconna(
    Alconna("退回红包"), aliases={"退还红包"}, priority=5, block=True, rule=ensure_group
)

_festive_matcher = on_alconna(
    Alconna(
        "节日红包",
        Args["amount", int]["num", int]["text?", str],
        Option("-g|--group", Args["group_list", str], help_text="指定群"),
    ),
    priority=1,
    block=True,
    permission=SUPERUSER,
    rule=to_me(),
)


@_red_bag_matcher.handle()
async def _(
    session: EventSession,
    arparma: Arparma,
    amount: int,
    num: int,
    user: Match[alcAt],
    default_interval: int = GetConfig(config="DEFAULT_INTERVAL"),
    user_name: str = UserName(),
):
    at_user = None
    if user.available:
        at_user = user.result.target
    # group_id = session.id3 or session.id2
    group_id = session.id2
    """以频道id为键"""
    user_id = session.id1
    if not user_id:
        await Text("用户id为空").finish()
    if not group_id:
        await Text("群组id为空").finish()
    group_red_bag = RedBagManager.get_group_data(group_id)
    # 剩余过期时间
    time_remaining = group_red_bag.check_timeout(user_id)
    if time_remaining != -1:
        # 判断用户红包是否存在且是否过时覆盖
        if user_red_bag := group_red_bag.get_user_red_bag(user_id):
            now = time.time()
            if now < user_red_bag.start_time + default_interval:
                await Text(
                    f"你的红包还没消化完捏...还剩下 {user_red_bag.num - len(user_red_bag.open_user)} 个! 请等待红包领取完毕..."
                    f"(或等待{time_remaining}秒红包cd)"
                ).finish()
    result = await RedBagManager.check_gold(user_id, amount, session.platform)
    if result:
        await Text(result).finish(at_sender=True)
    await group_red_bag.add_red_bag(
        f"{user_name}的红包",
        int(amount),
        1 if at_user else num,
        user_name,
        user_id,
        assigner=at_user,
        platform=session.platform,
    )
    image = await RedBagManager.random_red_bag_background(
        user_id, platform=session.platform
    )
    message_list: list = [
        Text(f"{user_name}发起了金币红包\n金额: {amount}\n数量: {num}\n")
    ]
    if at_user:
        message_list.append(Text("指定人: "))
        message_list.append(Mention(at_user))
        message_list.append(Text("\n"))
    message_list.append(Image(image.pic2bytes()))
    await MessageFactory(message_list).send()

    logger.info(
        f"塞入 {num} 个红包，共 {amount} 金币", arparma.header_result, session=session
    )


@_open_matcher.handle()
async def _(
    session: EventSession,
    rank_num: int = GetConfig(config="RANK_NUM"),
):
    # group_id = session.id3 or session.id2
    group_id = session.id2
    """以频道id为键"""
    user_id = session.id1
    if not user_id:
        await Text("用户id为空").finish()
    if not group_id:
        await Text("群组id为空").finish()
    if group_red_bag := RedBagManager.get_group_data(group_id):
        open_data, settlement_list = await group_red_bag.open(user_id, session.platform)
        # send_msg = Text("没有红包给你开！")
        send_msg = []
        for _, item in open_data.items():
            amount, red_bag = item
            result_image = await RedBagManager.build_open_result_image(
                red_bag, user_id, amount, session.platform
            )
            send_msg.append(
                Text(f"开启了 {red_bag.promoter} 的红包, 获取 {amount} 个金币\n")
            )
            send_msg.append(Image(result_image.pic2bytes()))
            send_msg.append(Text("\n"))
            logger.info(
                f"抢到了 {red_bag.promoter}({red_bag.promoter_id}) 的红包，获取了{amount}个金币",
                "开红包",
                session=session,
            )
        send_msg = (
            MessageFactory(send_msg[:-1]) if send_msg else Text("没有红包给你开！")
        )
        await send_msg.send(reply=True)
        if settlement_list:
            for red_bag in settlement_list:
                result_image = await red_bag.build_amount_rank(
                    rank_num, session.platform
                )
                await MessageFactory(
                    [Text(f"{red_bag.name}已结算\n"), Image(result_image.pic2bytes())]
                ).send()


@_return_matcher.handle()
async def _(
    session: EventSession,
    default_interval: int = GetConfig(config="DEFAULT_INTERVAL"),
    rank_num: int = GetConfig(config="RANK_NUM"),
):
    group_id = session.id3 or session.id2
    user_id = session.id1
    if not user_id:
        await Text("用户id为空").finish()
    if not group_id:
        await Text("群组id为空").finish()
    if group_red_bag := RedBagManager.get_group_data(group_id):
        if user_red_bag := group_red_bag.get_user_red_bag(user_id):
            now = time.time()
            if now - user_red_bag.start_time < default_interval:
                await Text(
                    f"你的红包还没有过时, 在 {int(default_interval - now + user_red_bag.start_time)} "
                    f"秒后可以退回..."
                ).finish(reply=True)
            user_red_bag = group_red_bag.get_user_red_bag(user_id)
            if user_red_bag and (
                data := await group_red_bag.settlement(user_id, session.platform)
            ):
                image_result = await user_red_bag.build_amount_rank(
                    rank_num, session.platform
                )
                logger.info(f"退回了红包 {data[0]} 金币", "红包退回", session=session)
                await MessageFactory(
                    [
                        Text(f"已成功退还了 " f"{data[0]} 金币\n"),
                        Image(image_result.pic2bytes()),
                    ]
                ).finish(reply=True)
    await Text("目前没有红包可以退回...").finish(reply=True)


@_festive_matcher.handle()
async def _(
    bot: Bot,
    session: EventSession,
    arparma: Arparma,
    amount: int,
    num: int,
    text: Match[str],
    group_list: Match[str],
    user_name: str = UserName(),
):
    # TODO: 指定多个群
    greetings = "恭喜发财 大吉大利"
    if text.available:
        greetings = text.result
    gl = []
    if group_list.available:
        gl = [group_list.result]
    else:
        g_l, platform = await PlatformUtils.get_group_list(bot)
        gl = [g.channel_id or g.group_id for g in g_l]
    _uuid = str(uuid.uuid1())
    FestiveRedBagManage.add(_uuid)
    for g in gl:
        if target := PlatformUtils.get_target(bot, group_id=g):
            group_red_bag = RedBagManager.get_group_data(g)
            if festive_red_bag := group_red_bag.get_festive_red_bag():
                group_red_bag.remove_festive_red_bag()
                if festive_red_bag.uuid:
                    FestiveRedBagManage.remove(festive_red_bag.uuid)
                rank_image = await festive_red_bag.build_amount_rank(10, platform)
                try:
                    await MessageFactory(
                        [
                            Text(
                                f"{NICKNAME}的节日红包过时了，一共开启了 "
                                f"{len(festive_red_bag.open_user)}"
                                f" 个红包，共 {sum(festive_red_bag.open_user.values())} 金币\n"
                            ),
                            Image(rank_image.pic2bytes()),
                        ]
                    ).send_to(target=target, bot=bot)
                except ActionFailed:
                    pass
            try:
                scheduler.remove_job(f"{FESTIVE_KEY}_{g}")
                await RedBagManager.end_red_bag(
                    g, is_festive=True, platform=session.platform
                )
            except JobLookupError:
                pass
            await group_red_bag.add_red_bag(
                f"{NICKNAME}的红包",
                amount,
                num,
                NICKNAME,
                FESTIVE_KEY,
                _uuid,
                platform=session.platform,
            )
            scheduler.add_job(
                RedBagManager._auto_end_festive_red_bag,
                "date",
                run_date=(datetime.now() + timedelta(hours=24)).replace(microsecond=0),
                id=f"{FESTIVE_KEY}_{g}",
                args=[bot, g, session.platform],
            )
            try:
                image_result = await RedBagManager.random_red_bag_background(
                    bot.self_id, greetings, session.platform
                )
                await MessageFactory(
                    [
                        Text(
                            f"{NICKNAME}发起了节日金币红包\n金额: {amount}\n数量: {num}\n"
                        ),
                        Image(image_result.pic2bytes()),
                    ]
                ).send_to(target=target, bot=bot)
                logger.debug("节日红包图片信息发送成功...", "节日红包", group_id=g)
            except ActionFailed:
                logger.warning(f"节日红包图片信息发送失败...", "节日红包", group_id=g)