from nonebot.adapters import Bot
from nonebot_plugin_uninfo import Session, SupportScope, Uninfo, get_interface

from zhenxun.configs.config import BotConfig
from zhenxun.models.ban_console import BanConsole
from zhenxun.models.bot_console import BotConsole
from zhenxun.models.group_console import GroupConsole
from zhenxun.models.task_info import TaskInfo
from zhenxun.services.log import logger


class CommonUtils:
    @classmethod
    async def task_is_block(
        cls, session: Uninfo | Bot, module: str, group_id: str | None = None
    ) -> bool:
        """判断被动技能是否可以发送

        参数:
            module: 被动技能模块名
            group_id: 群组id

        返回:
            bool: 是否可以发送
        """
        if isinstance(session, Bot):
            if interface := get_interface(session):
                info = interface.basic_info()
                if info["scope"] == SupportScope.qq_api:
                    logger.info("q官bot放弃所有被动技能发言...")
                    """q官bot放弃所有被动技能发言"""
                    return False
        if session.scene == SupportScope.qq_api:
            """q官bot放弃所有被动技能发言"""
            logger.info("q官bot放弃所有被动技能发言...")
            return False
        if not group_id and isinstance(session, Session):
            group_id = session.group.id if session.group else None
        if task := await TaskInfo.get_or_none(module=module):
            """被动全局状态"""
            if not task.status:
                return True
        if not await BotConsole.get_bot_status(session.self_id):
            """bot是否休眠"""
            return True
        block_tasks = await BotConsole.get_tasks(session.self_id, False)
        if module in block_tasks:
            """bot是否禁用被动"""
            return True
        if group_id:
            if await GroupConsole.is_block_task(group_id, module):
                """群组是否禁用被动"""
                return True
            if g := await GroupConsole.get_or_none(
                group_id=group_id, channel_id__isnull=True
            ):
                """群组权限是否小于0"""
                if g.level < 0:
                    return True
            if await BanConsole.is_ban(None, group_id):
                """群组是否被ban"""
                return True
        return False


class SqlUtils:
    @classmethod
    def random(cls, query, limit: int = 1) -> str:
        db_class_name = BotConfig.get_sql_type()
        if "postgres" in db_class_name or "sqlite" in db_class_name:
            query = f"{query.sql()} ORDER BY RANDOM() LIMIT {limit};"
        elif "mysql" in db_class_name:
            query = f"{query.sql()} ORDER BY RAND() LIMIT {limit};"
        else:
            logger.warning(
                f"Unsupported database type: {db_class_name}", query.__module__
            )
        return query
