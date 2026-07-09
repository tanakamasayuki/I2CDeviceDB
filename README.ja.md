# I2CDeviceDB

**I2CDeviceDB** は、I2C デバイスの実機通信を収集・整理・公開するためのオープンなデータ基盤プロジェクトです。

I2C ライブラリでもデバイスエミュレータでもありません。それらを開発しやすくするための **データ資産** を作ることが目的です。実機から取得した通信を長期間再利用できる形で蓄積し、ライブラリ開発・エミュレータ開発・テスト自動化・プロトコル解析・教育などの共通基盤とすることを目指します。

> 本リポジトリのドキュメントは現時点の設計方針を示す **叩き台** です。決定済みの事項と、収集を進めながら調整する事項が混在します。各ドキュメント冒頭のステータスを参照してください。

## メインターゲット

汎用的に使えるデータを目指しますが、当初のメインターゲットは **M5Stack 社の Unit** です。ファーストターゲットは `m5stack-u001`（ENV Unit / DHT12 + BMP280）で、ここで収集 → デコード → 比較のパイプライン全体を通します。

## 基本アイデア

- 収集は **「1 ライブラリ × 1 チップ」= 1 probe** 単位（1 スケッチ 1 ライブラリで 1 チップを叩く。ライブラリ同居なし）。
- **キャプチャは chip 単位（chip-scoped）で製品非依存**。物理的には製品（Unit）を接続して取るが、データはそのチップに紐づき、同じチップを含む他製品で使い回せる（例: BMP280 のデータは U001 でも ENV IV でも共通）。
- **product は部品表**（どの chip がどのアドレスに載るか）。「製品ビュー」はその製品のチップのデータを集約して作る。
- 同じチップを **複数ライブラリで取得して通信を比較**できる（例: BMP280 を M5Unit-ENV ↔ Adafruit）。

詳細は [docs/SPEC.ja.md](docs/SPEC.ja.md) を参照してください。

## リポジトリ構成

仕様（docs）・データ（chips / libraries / products）・収集ハーネス（collection）で構成。captures・サイトは docs に設計を置き、実装時に追加する。

```text
chips/        I2C チップ定義（マスタ。1チップ1 YAML）
libraries/    ライブラリレジストリ（マスタ。1ライブラリ1 YAML）
products/     製品定義（マスタ。1製品1 YAML）
docs/         仕様・データモデル・収集/サイト設計（当面日本語）
collection/   uv プロジェクト。pytest ＋ sigrok 制御 ＋ probe が同居  → docs/COLLECTION.ja.md
```

実装時に追加予定（設計は docs 参照）:

```text
captures/     収集した通信データ raw / decoded（collection の出力）    → docs/DATA_MODEL.ja.md
tools/        オフライン処理（デコード / 比較 / サイト生成）           → docs/SITE.ja.md
```

`collection/` は uv プロジェクトのルートで、配下に probe（`<chip>__<library>` のスケッチ）が入る。**probe は増減するのでここには列挙しない** — 一覧・命名規則・実行方法は [collection/README.ja.md](collection/README.ja.md) と [docs/COLLECTION.ja.md](docs/COLLECTION.ja.md) を参照。現状 probe は `scan`（全アドレス掃引）のみ。

データは YAML をマスタとし、ビルドで JSON を生成。サイトは GitHub Actions で gh-pages ブランチに公開する（[docs/SITE.ja.md](docs/SITE.ja.md)）。生成物は main に置かない。

## ドキュメント

- [docs/SPEC.ja.md](docs/SPEC.ja.md) — 仕様書（目的・対象・方針の全体像）
- [docs/DATA_MODEL.ja.md](docs/DATA_MODEL.ja.md) — データモデル（chips / products / libraries / captures と連結、YAML マスタ）
- [docs/COLLECTION.ja.md](docs/COLLECTION.ja.md) — 収集の設計（collection: ハードウェア構成・sigrok・UART マーカー・probe スケッチ）
- [docs/SITE.ja.md](docs/SITE.ja.md) — サイト / 公開設計（gh-pages・静的生成 + クライアント描画）

## ライセンス

コードとドキュメントは [MIT License](LICENSE)。収録するデータは再配布可能なもののみとします（[docs/SPEC.ja.md](docs/SPEC.ja.md) のライセンス節を参照）。
