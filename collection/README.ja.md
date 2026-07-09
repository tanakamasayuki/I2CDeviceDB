# collection

I2CDeviceDB の収集ハーネス（uv + pytest ＋ sigrok ＋ Arduino probe）。設計は
[../docs/COLLECTION.ja.md](../docs/COLLECTION.ja.md) を参照。

pytest は pass/fail 判定器ではなく **収集オーケストレータ**として使う。probe を
書き込み・実行し、`--continuous` + SIGINT で sigrok キャプチャを run に張り付け、
`_staging/` に `.sr` を残す。デコード → 内容ハッシュ命名 → `captures/` への永続化は
オフラインの別工程（`tools/`、未実装）。

## セットアップ

```sh
cd collection
uv sync
cp .env.example .env   # 自分のベンチに合わせて編集
```

`.env` の要点（詳細は `.env.example`）:

- `TEST_SERIAL_PORT_<PROFILE>` — ESP のシリアルポート（PROFILE = `sketch.yaml` の profile を大文字化）。
- `TEST_I2C_SDA` / `TEST_I2C_SCL` / `TEST_UART_TX` — probe の GPIO（`build_config.toml` 経由で define 注入）。
- `SIGROK_DRIVER` / `SIGROK_CONN` / `SIGROK_SAMPLERATE` — sigrok 設定（conn は空なら渡さない、samplerate 既定 8MHz）。
- `SIGROK_CH_<SIGNAL>` — 信号ごとの物理チャネル。probe が要る信号だけ `--channels` に合成。

## 実行

```sh
# 製品を指定 → 必要な probe セット（scan ＋ chip×対応ライブラリ）を導出して実行
uv run --env-file .env pytest --product m5stack-u001

# 何が回るか確認（ハード不要）
uv run pytest --collect-only --product m5stack-u001

# 単一 probe / 部分実行は通常のテスト選択で
uv run --env-file .env pytest sketches/scan
```

## probe の追加

1 probe = 1 スケッチフォルダ（`sketches/<probe>/`）にスケッチとテストを同居させる。
`<probe>` は `scan` か `<chip>__<library>`。

```
sketches/<probe>/
  <probe>.ino          # GPIO は #ifndef フォールバック + atoi（define で上書き）
  sketch.yaml          # profile / fqbn / platform
  build_config.toml    # [defines] で .env 変数 -> #define 名
  test_*.py            # @pytest.mark.probe("<probe>") を付けて駆動
```

`@pytest.mark.probe("<probe>")` を付けると `--product` の導出セットと突き合わせて選択される。
現状は `scan`（全アドレス掃引）のみ実装。
