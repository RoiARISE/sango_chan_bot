import asyncio
from misskey import Misskey
from bot import MyBot
import sango_chan_bot.config as config

msk = Misskey(config.INSTANCE_URL, i=config.TOKEN)
ADMIN_ID = config.ADMIN_ID

if __name__ == "__main__":
    sango_chan = MyBot()
    try:
        asyncio.run(sango_chan.main_task())
    except KeyboardInterrupt:
        msk.notes_create(text="うとうと……")
        print("botを停止します")
