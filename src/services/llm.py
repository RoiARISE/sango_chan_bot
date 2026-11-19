import asyncio
import logging

from . import openrouter
from ..stores.user_store import UserStore
from ..utils import Audience

logger = logging.getLogger(__name__)

# 記憶を保存する辞書（botが起動している間だけ保持されます）
user_memories: dict = {}
# 各発言をどの聴衆のノートで交わしたか（user_memories と同じ長さ・同じ順序）
user_memory_audiences: dict[str, list[Audience]] = {}
# ユーザーごとの連続会話で何往復完了したかを記録する辞書
user_turns: dict[str, int] = {}
# user_memories[user_id] のうちプロフィール/親密度分析へ回し終えた先頭件数
user_analyzed_upto: dict[str, int] = {}
# ユーザーごとのデバウンス待機タイマー
user_profile_timers: dict[str, asyncio.Task] = {}
# デバウンス待機中の更新対象 (user_name, store)
_pending_profile_targets: dict[str, tuple[str, UserStore]] = {}
# 実行中のバックグラウンドプロフィール更新タスク
_active_profile_update_tasks: set[asyncio.Task] = set()
# ユーザーごとのバックグラウンドプロフィール更新直列化ロック
user_profile_update_locks: dict[str, asyncio.Lock] = {}
# ユーザーごとの排他ロック
user_locks: dict[str, asyncio.Lock] = {}
# 過去何往復分の会話を覚えているか（いまのところ10件＝5往復に制限）
MAX_HISTORY = 10
# 連続会話の安全上限（往復数）。これを超えると強制的にリアクションで終了する
MAX_TURNS = 8
# reply 終了後に次の返信が無ければ会話一区切りとみなすデバウンス待機秒数
PROFILE_UPDATE_DELAY = 60.0

# 聴衆が分からない発言は、最も狭いものとして扱う（fail-closed）
_UNKNOWN_AUDIENCE = Audience("unknown")


def _align_audiences(user_id: str) -> list[Audience]:
    """履歴の長さに聴衆リストを合わせる。

    直接履歴が差し替えられた場合は、情報の無いターンを unknown で埋める。
    unknown はどの聴衆も包含しないので、LLM には渡らない。
    """
    history = user_memories.setdefault(user_id, [])
    audiences = user_memory_audiences.setdefault(user_id, [])
    if len(audiences) < len(history):
        audiences.extend([_UNKNOWN_AUDIENCE] * (len(history) - len(audiences)))
    elif len(audiences) > len(history):
        del audiences[len(history):]
    return audiences


def _append_turn(user_id: str, message: dict, audience: Audience) -> None:
    audiences = _align_audiences(user_id)
    user_memories[user_id].append(message)
    audiences.append(audience)


def _drop_last_turn(user_id: str) -> None:
    audiences = _align_audiences(user_id)
    if user_memories.get(user_id):
        user_memories[user_id].pop()
    if audiences:
        audiences.pop()
    if user_id in user_analyzed_upto:
        user_analyzed_upto[user_id] = min(
            user_analyzed_upto[user_id], len(user_memories.get(user_id, []))
        )


def _reset_history(user_id: str) -> None:
    user_memories[user_id] = []
    user_memory_audiences[user_id] = []
    user_turns[user_id] = 0
    user_analyzed_upto[user_id] = 0


def _truncate_history(user_id: str) -> None:
    audiences = _align_audiences(user_id)
    overflow = len(user_memories[user_id]) - MAX_HISTORY
    if overflow > 0:
        user_memories[user_id] = user_memories[user_id][-MAX_HISTORY:]
        user_memory_audiences[user_id] = audiences[-MAX_HISTORY:]
        user_analyzed_upto[user_id] = max(0, user_analyzed_upto.get(user_id, 0) - overflow)


def _visible_history(user_id: str, audience: Audience) -> list[dict]:
    """今の聴衆にも見えていた発言だけを返す。"""
    history = user_memories.get(user_id, [])
    audiences = _align_audiences(user_id)
    return [
        message
        for message, recorded in zip(history, audiences)
        if recorded.covers(audience)
    ]


def _session_is_public_only(user_id: str) -> bool:
    """このセッションの全発言が誰でも閲覧できるノートで交わされたか。

    home は配信範囲の違いで閲覧できる人は public と同じなので含める。
    プロフィール要約は発言内容をそのまま含むため、非公開の会話が
    1 つでも混ざっていれば更新しない。
    """
    return all(audience.is_public for audience in _align_audiences(user_id))


async def _update_user_profile_in_background(
    user_id: str,
    user_name: str,
    history: list,
    current_profile: str,
    current_intimacy: int,
    store: UserStore,
    *,
    delay: float = 5.0,
    refresh_from_store: bool = False,
) -> None:
    try:
        # 返信直後の連続リクエストによるクォータ超過(429)を避けるため少し待機
        if delay > 0:
            await asyncio.sleep(delay)

        update_lock = user_profile_update_locks.setdefault(user_id, asyncio.Lock())
        async with update_lock:
            profile = store.get_profile(user_id) if refresh_from_store else current_profile
            intimacy = store.get_intimacy(user_id) if refresh_from_store else current_intimacy
            analysis = await openrouter.analyze_user_interaction(
                history, profile, intimacy, user_name
            )
            new_profile = analysis.get("description")
            intimacy_change = analysis.get("intimacy_change", 0)

            if new_profile:
                store.set_profile(user_id, new_profile, user_name)
                logger.info("[%s] プロファイルを更新しました: %s", user_name, new_profile)

            if intimacy_change != 0:
                new_intimacy, applied = store.change_intimacy(user_id, intimacy_change, user_name)
                if applied:
                    logger.info(
                        "[%s] 親密度が変化しました: %d (%+d)",
                        user_name,
                        new_intimacy,
                        intimacy_change
                    )
                else:
                    logger.info(
                        "[%s] 親密度の上昇要求がありましたが、1日1回の制限のため適用されませんでした。(現在: %d)",
                        user_name,
                        new_intimacy
                    )
    except Exception:
        logger.error("[%s] プロファイル/親密度更新中にエラーが発生しました", user_name, exc_info=True)


def _cancel_profile_timer(user_id: str) -> None:
    _pending_profile_targets.pop(user_id, None)
    task = user_profile_timers.pop(user_id, None)
    if task is not None and not task.done():
        task.cancel()


def _schedule_profile_update(
    user_id: str,
    user_name: str,
    store: UserStore | None,
    current_profile: str | None = None,
    current_intimacy: int | None = None,
    *,
    delay: float = 5.0,
) -> asyncio.Task | None:
    """公開会話のみの未分析セッションがあればバックグラウンドでプロフィール/親密度更新を予約する。"""
    history = user_memories.get(user_id)
    if store is None or not history:
        return None
    upto = min(user_analyzed_upto.get(user_id, 0), len(history))
    if upto >= len(history):
        return None
    if not _session_is_public_only(user_id):
        logger.info("[%s] 非公開の会話を含むためプロフィール/親密度の更新をスキップします", user_name)
        return None

    unanalyzed = list(history[upto:])
    user_analyzed_upto[user_id] = len(history)
    profile = store.get_profile(user_id) if current_profile is None else current_profile
    intimacy = store.get_intimacy(user_id) if current_intimacy is None else current_intimacy
    task = asyncio.create_task(
        _update_user_profile_in_background(
            user_id,
            user_name,
            unanalyzed,
            profile,
            intimacy,
            store,
            delay=delay,
            refresh_from_store=True,
        )
    )
    _active_profile_update_tasks.add(task)
    task.add_done_callback(_active_profile_update_tasks.discard)
    return task


async def _debounced_profile_update_worker(
    user_id: str, user_name: str, store: UserStore
) -> None:
    try:
        if PROFILE_UPDATE_DELAY > 0:
            await asyncio.sleep(PROFILE_UPDATE_DELAY)
        lock = user_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            _pending_profile_targets.pop(user_id, None)
            _schedule_profile_update(user_id, user_name, store, delay=0.0)
    except asyncio.CancelledError:
        pass
    finally:
        current = asyncio.current_task()
        if user_profile_timers.get(user_id) is current:
            user_profile_timers.pop(user_id, None)
            _pending_profile_targets.pop(user_id, None)


def _schedule_debounced_profile_update(
    user_id: str, user_name: str, store: UserStore | None
) -> None:
    """reply 終了後、次の返信が無ければ一区切りとみなしてプロフィール更新を実行するタイマーを予約する。"""
    _cancel_profile_timer(user_id)
    history = user_memories.get(user_id)
    if store is None or not history:
        return
    upto = min(user_analyzed_upto.get(user_id, 0), len(history))
    if upto >= len(history):
        return
    _pending_profile_targets[user_id] = (user_name, store)
    user_profile_timers[user_id] = asyncio.create_task(
        _debounced_profile_update_worker(user_id, user_name, store)
    )


async def flush_pending_profile_updates(timeout: float = 5.0) -> None:
    """デバウンス待機中および実行中のプロフィール更新を即時フラッシュし、完了を待つ。"""
    pending = list(_pending_profile_targets.items())
    for user_id, (user_name, store) in pending:
        _cancel_profile_timer(user_id)
        lock = user_locks.setdefault(user_id, asyncio.Lock())
        if not lock.locked():
            async with lock:
                _schedule_profile_update(user_id, user_name, store, delay=0.0)
        else:
            _schedule_profile_update(user_id, user_name, store, delay=0.0)

    tasks = [t for t in _active_profile_update_tasks if not t.done()]
    if tasks:
        _, pending_tasks = await asyncio.wait(tasks, timeout=timeout)
        for task in pending_tasks:
            task.cancel()


def clear_runtime_state() -> None:
    """インメモリ会話状態と待機中タイマーをすべて初期化する（主にテスト用）。"""
    for task in list(user_profile_timers.values()):
        if not task.done():
            task.cancel()
    for task in list(_active_profile_update_tasks):
        if not task.done():
            task.cancel()
    user_memories.clear()
    user_memory_audiences.clear()
    user_turns.clear()
    user_analyzed_upto.clear()
    user_profile_timers.clear()
    _pending_profile_targets.clear()
    _active_profile_update_tasks.clear()
    user_profile_update_locks.clear()
    user_locks.clear()


async def run_llm(
    user_id: str,
    user_name: str,
    text: str,
    is_reply: bool = False,
    store: UserStore | None = None,
    image_urls: list[str] | None = None,
    has_sensitive_image: bool = False,
    intent_hint: str = "",
    audience: Audience | None = None,
) -> dict:
    """
    botから呼び出されるLLM実行関数。
    ユーザーIDと名前を受け取り、会話履歴を管理し、行動アクションを含む辞書を返す。

    ``is_reply`` が True のときだけ過去の会話履歴を引き継ぐ（スレッド継続）。
    False のときは新規の会話として履歴をリセットする。

    ``audience`` は今回のノートの聴衆。履歴のうち、これより狭い聴衆に
    しか見えていなかった発言は LLM に渡さない。省略された場合は
    聴衆不明として扱い、public 以外の履歴を渡さない（fail-closed）。
    """
    global user_memories, user_locks

    current_audience = audience if audience is not None else _UNKNOWN_AUDIENCE

    lock = user_locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        # 新規メンション（リプライではない）なら、未分析の前回会話を回収したうえで記憶を消去
        if not is_reply:
            _cancel_profile_timer(user_id)
            _schedule_profile_update(user_id, user_name, store)
            _reset_history(user_id)
            logger.debug("[%s] 新規メンションのため記憶をリセットしました", user_name)

        # LLMに「誰からのメッセージか」を意識させるために名前を差し込む
        display_text = text.strip() if text and text.strip() else ""
        if not display_text and image_urls:
            display_text = "（画像が送信されました）"

        prompt_with_name = f"[{user_name}さんからのメッセージ]\n{display_text}"
        if image_urls:
            prompt_with_name += "\n[画像が添付されています]"
            if has_sensitive_image:
                prompt_with_name += " (注: センシティブ指定されている画像です)"

        # 今回の聴衆にも見えていた履歴だけを使う
        visible_history = _visible_history(user_id, current_audience)

        # ターン数（往復回数）の計算（MAX_HISTORY で履歴を切り捨てても正しく進めるため専用カウンタを使う）
        current_turn = user_turns.get(user_id, 0) + 1

        # コスト爆発防止の安全弁（保険: MAX_TURNS往復を超えたら強制リアクション終了）
        if current_turn > MAX_TURNS:
            logger.info("[%s] 会話ターン数が安全上限(%d)に達したため、リアクションで会話を終了します", user_name, current_turn)
            _cancel_profile_timer(user_id)
            _schedule_profile_update(user_id, user_name, store)
            _reset_history(user_id)
            return {
                "action": "react",
                "reaction": "💤",
                "reply": "",
                "reason": "safety_turn_limit_reached",
            }

        # 履歴にはテキスト情報のみを保存（トークン肥大化と分析エラーを防ぐ）
        _append_turn(
            user_id,
            {"role": "user", "content": prompt_with_name},
            current_audience,
        )
        messages_for_llm = visible_history + [user_memories[user_id][-1]]

        # ユーザープロフィールと親密度をストアから取得
        user_profile = ""
        intimacy = 0
        if store is not None:
            user_profile = store.get_profile(user_id)
            intimacy = store.get_intimacy(user_id)

        # 会話進行コンテキストの生成
        convo_context = f"現在この相手とのスレッドでのやりとりは {current_turn} ターン目です。"
        if not is_reply:
            convo_context += (
                " これは相手からの新規メンション（1ターン目の最初の呼びかけ）であり、"
                "あなたはまだ一度も返事をしていません。挨拶や短い言葉であっても、"
                "まずはリアクションだけで終わらせず言葉で返信（reply）してください。"
            )
        elif current_turn >= 4:
            convo_context += " 話題が一区切りついている場合は、無理に会話を続けず react（リアクションのみで終了）を選択してフェードアウトしてください。"

        try:
            result = await openrouter.chat_with_history(
                messages_for_llm,
                user_profile=user_profile,
                intimacy=intimacy,
                image_urls=image_urls,
                convo_context=convo_context,
                intent_hint=intent_hint,
            )

            action = result.get("action", "reply")
            reply_text = result.get("reply", "")

            if action == "reply":
                _append_turn(
                    user_id,
                    {"role": "assistant", "content": reply_text},
                    current_audience,
                )
                user_turns[user_id] = current_turn
                # 記憶が上限を超えたら、古いものから忘れる
                _truncate_history(user_id)
                _schedule_debounced_profile_update(user_id, user_name, store)
            elif action in ("react", "none"):
                # 会話がフェードアウト（終了）したため、タイマーを止めて未分析分を即座に更新
                _cancel_profile_timer(user_id)
                _schedule_profile_update(user_id, user_name, store, user_profile, intimacy)
                # 会話終了につきメモリをクリア
                _reset_history(user_id)

            return result
        except Exception as e:
            if user_memories.get(user_id):
                _drop_last_turn(user_id)
            return {
                "action": "reply",
                "reaction": "⚠️",
                "reply": f"ごめん、LLMでエラーが起きちゃったみたい…\n`{e}`",
                "reason": "run_llm_exception",
            }
