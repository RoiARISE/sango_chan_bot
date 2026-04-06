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
    try:
        asyncio.run(sango_chan.main_task())
    except KeyboardInterrupt:
        msk.notes_create(text="うとうと……")
        logger.info("botを停止します")
