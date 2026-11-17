import asyncio
import logging

from misskey import Misskey

from . import config
from .bot import MyBot
from .logger import setup_logging
from .services import llm

setup_logging()
logger = logging.getLogger(__name__)

msk = Misskey(config.INSTANCE_URL, i=config.TOKEN)

if __name__ == "__main__":
    sango_chan = MyBot(msk)

    async def _run():
        try:
            await asyncio.gather(
                sango_chan.main_task(),
                sango_chan.timesignal_task(),
                sango_chan.relationship_cleanup_task(),
            )
        finally:
            try:
                await llm.flush_pending_profile_updates(timeout=5.0)
            except Exception:
                logger.warning("終了時のプロフィール更新フラッシュに失敗しました", exc_info=True)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        msk.notes_create(text="うとうと……")
        logger.info("botを停止します")
