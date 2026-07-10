# collection

I2CDeviceDB の収集ハーネス（uv + pytest ＋ sigrok ＋ Arduino probe）。設計は
[../docs/COLLECTION.ja.md](../docs/COLLECTION.ja.md) を参照。

pytest は実測値の pass/fail 判定器ではなく **収集オーケストレータ**として使う。probe を
書き込み・実行し、`--continuous` + SIGINT で sigrok キャプチャを run に張り付け、
`_staging/` に `.sr` を残す。既存実装の利用経路を記録する library probe に加え、
低レベル I2C と宣言的 scenario で状態・副作用・timing を確認する characterization probe を
同じパイプラインで駆動する。U001-C の characterization は provisional observation JSON まで
`_staging/` に生成する。デコード → curated observation 作成 → 内容ハッシュ命名 →
`captures/` への永続化はオフラインの別工程（`tools/`、未実装）。

## セットアップ

```sh
cd collection
uv sync
cp .env.example .env   # 自分のベンチに合わせて編集
```

`.env` の要点（詳細は `.env.example`）:

- `TEST_SERIAL_PORT_<PROFILE>` — ESP のシリアルポート（PROFILE = `sketch.yaml` の profile を大文字化）。
- `TEST_I2C_SDA` / `TEST_I2C_SCL` / `TEST_UART_TX` — probe の GPIO（`build_config.toml` 経由で define 注入）。
- `TEST_I2C_BUS_HZ` — characterization の I2C clock。初回は `100000`、次に `400000` で別 run。
- `TEST_PRODUCT` / `TEST_SPECIMEN_ID` — observation provenance。characterization では必須。
- `SIGROK_DRIVER` / `SIGROK_CONN` / `SIGROK_SAMPLERATE` — sigrok 設定（conn は空なら渡さない、samplerate 既定 8MHz）。
- `SIGROK_CH_<SIGNAL>` — 信号ごとの物理チャネル。probe が要る信号だけ `--channels` に合成。

## 実行

```sh
# 製品を指定 → scan + SHT30/QMP6988 characterizationを導出して実行
uv run --env-file .env pytest --product m5stack-u001-c

# 何が回るか確認（ハード不要）
uv run pytest --collect-only --product m5stack-u001-c

# 単一 probe / 部分実行は通常のテスト選択で
uv run --env-file .env pytest sketches/scan
uv run --env-file .env pytest sketches/sht30__characterize
uv run --env-file .env pytest sketches/qmp6988__characterize

# ハード不要の収集モデルテスト
uv run pytest -q unit_tests
```

正常終了後、`_staging/` に probe ごとの `.sr`、`.jsonl`、
`<probe>.observation.json` が残る。observation JSON は schema 検討中の候補であり、
レビューせず `observations/` へコピーしない。

## 到着前のコンパイル確認

```sh
arduino-cli core install esp32:esp32@3.3.10 \
  --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli compile --fqbn esp32:esp32:esp32s3 sketches/sht30__characterize
arduino-cli compile --fqbn esp32:esp32:esp32s3 sketches/qmp6988__characterize
```

Ubuntu で `sigrok-cli` が未導入なら、到着後の実行前にインストールする。

```sh
sudo apt install sigrok-cli
```

```sh
sigrok-cli --scan
```

デバイスが見つからない場合、`fx2lafw-cypress-fx2.fw` のファームウェアがロードできていない。

```sh
sudo apt install sigrok-firmware-fx2lafw
```

`sigrok-firmware-fx2lafw` を apt で入れた後、USB ケーブルを抜き差しして再試行する。

`.env` 設定だけを確認する offline preflight と、機材接続後の完全 preflight:

```sh
uv run --env-file .env python preflight.py --offline
uv run --env-file .env python preflight.py
```

## library probe の追加

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
characterization の scenario / runner / adapter の配置と安全規約は
[../docs/COLLECTION.ja.md](../docs/COLLECTION.ja.md) を参照。
