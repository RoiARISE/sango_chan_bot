from asyncio import to_thread

import speedtest as speedtest_lib


async def run_speedtest() -> str:
    """回線速度を計測する非同期関数"""
    try:
        st = speedtest_lib.Speedtest(secure=True)
        await to_thread(st.get_best_server)
        download_speed = await to_thread(st.download) / 1_000_000  # Mbps
        upload_speed = await to_thread(st.upload) / 1_000_000  # Mbps
        ping = st.results.ping
        return f"計測かんりょー。下り{download_speed:.2f}Mbps、上り{upload_speed:.2f}Mbps、ping値{ping:.2f}msだったよ。……これは速いって言えるのかな？"
    except Exception as e:
        return f"ごめん、計測中にエラーが起きちゃったみたい……\n`{e}`"
