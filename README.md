# README りーどみー
## さんごちゃんbotとは？
Roi_ARISEによって創作された敷島ロイの子。できることは[wiki](https://github.com/RoiARISE/sango_chan_bot/wiki)より。

# MyMisskeyBot

このbotはMisskey.pyを使用しています。[Misskey.py](https://github.com/YuzuRyo61/Misskey.py).

## ログ

ロギングには [structlog](https://www.structlog.org/) を使っています。標準の `logging` と
`structlog.get_logger()` のどちらから出力しても同じ形式になります。

デフォルトは人間が読みやすいテキスト形式です。`.env` で `LOG_FORMAT="json"` を指定すると、
1行1レコードのJSON形式（JSON Lines）で出力されます。

```json
{"message":"botが起動しました","logger":"src.bot","level":"info","timestamp":"2026-11-11T21:00:00.000+09:00"}
```

JSONログには `message` / `logger` / `level` / `timestamp` に加え、`extra={"user_id": ...}` や
structlog のキーワード引数で渡したフィールド、例外発生時の `exception`（スタックトレース）が含まれます。

## ライセンス
このプロジェクトのソースコードは MIT License を基本とします。

## クレジット
- **Misskey.py** by [YuzuRyo61](https://github.com/YuzuRyo61/Misskey.py) (MIT)
- 参考記事: [CyberRex on Qiita](https://qiita.com/CyberRex/items/e49828dba8e5867d8b26)
- 一部のコードは ChatGPT (OpenAI) と Gemini (Google) を参考にして作りました
