# I2CDeviceDB

**I2CDeviceDB** は、I2C デバイスの実機通信と振る舞いを収集・整理・公開するためのオープンなデータ基盤プロジェクトです。

I2C ライブラリでもデバイスエミュレータでもありません。それらを自動生成・検証できる **証拠付きのデバイス行動データ** を作ることが目的です。生キャプチャだけでなく、レジスタ、値の意味、副作用、状態遷移、タイミングなどを機械可読な chip profile として整備し、ライブラリ開発・エミュレータ開発・テスト自動化・プロトコル解析・教育などの共通基盤とします。

責務の境界は次のとおりです。

- このリポジトリは、正規化された chip profile、その根拠となる observation / capture、実機 characterization と既存ライブラリ probe、検証用テストベクターを持つ。
- 特定言語向けアクセスライブラリ、特定 MCU / OS 向けエミュレータランタイム、配布パッケージは派生プロジェクトが持つ。
- 既存ライブラリの通信は重要な互換性証拠だが、chip profile の正本ではない。未使用機能や状態遷移は characterization probe で直接確認する。

> 本リポジトリのドキュメントは現時点の設計方針を示す **叩き台** です。決定済みの事項と、収集を進めながら調整する事項が混在します。各ドキュメント冒頭のステータスを参照してください。

## メインターゲット

汎用的に使えるデータを目指しますが、当初のメインターゲットは **M5Stack 社の Unit** です。ファーストターゲットは `m5stack-u001-c`（ENV III / SHT30 + QMP6988）で、command 型の SHT30 と register-map 型の QMP6988を使い、収集 → profile 整理 → ライブラリ / エミュレータ生成 → conformance のパイプライン全体を通します。

## 基本アイデア

- 収集は、実装の利用パターンを記録する **library probe** と、デバイスを直接操作して振る舞いを確認する **characterization probe** の二系統。
- **chip profile が生成器の正本**。仕様書由来・実測・推定を区別し、根拠 observation へリンクする。
- chip は **基本カタログを先に広く登録し、詳細 profile を後から深掘りする**。編集用 YAML は `chips/<key>.yaml` と `profiles/<key>.yaml` に分け、公開時に chip 単位の JSON へ統合する。
- **キャプチャは chip 単位（chip-scoped）で製品非依存**。物理的には製品（Unit）を接続して取るが、データはそのチップに紐づき、同じチップを含む他製品で使い回せる（例: BMP280 のデータは U001 でも ENV IV でも共通）。
- **product は部品表**（どの chip がどのアドレスに載るか）。「製品ビュー」はその製品のチップのデータを集約して作る。
- 同じチップを **複数ライブラリで取得して通信を比較**できる（例: BMP280 を M5Unit-ENV ↔ Adafruit）。
- 利用者向けライブラリとエミュレータは、公開 JSON とテストベクターを読む別プロジェクトとして実装する。

詳細は [docs/SPEC.ja.md](docs/SPEC.ja.md) を参照してください。

## リポジトリ構成

仕様（docs）・データ（chips / libraries / products）・収集ハーネス（collection）で構成。captures・サイトは docs に設計を置き、実装時に追加する。

```text
chips/        I2C チップの基本カタログ（識別・検索・製品との連結）
profiles/     生成用の詳細な chip 行動仕様（任意、追加予定）
libraries/    ライブラリレジストリ（マスタ。1ライブラリ1 YAML）
products/     製品定義（マスタ。1製品1 YAML）
scenarios/    実機 characterization の宣言的シナリオ
observations/ 実験入力・結果・provenance・capture 参照（追加予定）
docs/         仕様・データモデル・収集/サイト設計（当面日本語）
collection/   uv プロジェクト。pytest ＋ sigrok 制御 ＋ probe が同居  → docs/COLLECTION.ja.md
```

実装時に追加予定（設計は docs 参照）:

```text
captures/     収集した通信データ raw / decoded（collection の出力）    → docs/DATA_MODEL.ja.md
tools/        オフライン処理（デコード / 比較 / サイト生成）           → docs/SITE.ja.md
```

`collection/` は uv プロジェクトのルートで、配下に library probe（`<chip>__<library>`）と characterization probe（`<chip>__characterize`）のスケッチが入る。**probe は増減するのでここには列挙しない** — 一覧・命名規則・実行方法は [collection/README.ja.md](collection/README.ja.md) と [docs/COLLECTION.ja.md](docs/COLLECTION.ja.md) を参照。U001-C 向けには `scan`、`sht30__characterize`、`qmp6988__characterize` を実装済み。

データは YAML をマスタとし、ビルドで JSON を生成。サイトは GitHub Actions で gh-pages ブランチに公開する（[docs/SITE.ja.md](docs/SITE.ja.md)）。生成物は main に置かない。

## ドキュメント

- [docs/SPEC.ja.md](docs/SPEC.ja.md) — 仕様書（目的・対象・方針の全体像）
- [docs/DATA_MODEL.ja.md](docs/DATA_MODEL.ja.md) — データモデル（chips / products / libraries / captures と連結、YAML マスタ）
- [docs/COLLECTION.ja.md](docs/COLLECTION.ja.md) — 収集の設計（collection: ハードウェア構成・sigrok・UART マーカー・probe スケッチ）
- [docs/SITE.ja.md](docs/SITE.ja.md) — サイト / 公開設計（gh-pages・静的生成 + クライアント描画）
- [docs/pilots/m5stack-u001-c.md](docs/pilots/m5stack-u001-c.md) — ENV III pilot checklist（SHT30 / QMP6988 の調査・収集・生成実証）

## ライセンス

コードとドキュメントは [MIT License](LICENSE)。収録するデータは再配布可能なもののみとします（[docs/SPEC.ja.md](docs/SPEC.ja.md) のライセンス節を参照）。
