import asyncio
import logging

from misskey import Misskey

from . import config
from .bot import MyBot
from .logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

msk = Misskey(config.INSTANCE_URL, i=config.TOKEN)

if __name__ == "__main__":
    sango_chan = MyBot(msk)

    async def _run():
        await asyncio.gather(
            sango_chan.main_task(),
            sango_chan.timesignal_task(),
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        msk.notes_create(text="うとうと……")
        logger.info("botを停止します")
