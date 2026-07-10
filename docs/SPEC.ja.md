# I2CDeviceDB 仕様書

> ステータス: 叩き台。目的・方針は概ね確定。データ 5 層の粒度や語彙は収集を進めながら調整する。

## 概要

**I2CDeviceDB** は、I2C デバイスの通信と振る舞いを収集・整理・公開するためのオープンなデータベースプロジェクトです。実機から取得した I2C 通信を一次証拠として蓄積し、レジスタ、値の意味、副作用、状態遷移、タイミングを機械可読な chip profile に整理します。各種ライブラリ・エミュレータ・テストツール・プロトコル解析ツールが自動生成・検証に利用できる共通基盤となることを目的とします。

I2CDeviceDB 自身は I2C ライブラリやデバイスエミュレータではなく、それらを開発しやすくするための **データ基盤** です。

## 目的

- I2C デバイスの通信データと行動仕様をオープンに蓄積する
- 実機から取得した通信を長期間利用できる形で保存する
- デバイスごとの転送方式、レジスタ、値の意味、副作用、状態遷移、タイミングを体系化する
- エミュレータとデバイスアクセスライブラリを自動生成できる中立なデータモデルを整備する
- 各仕様項目を、仕様書・実測 observation・推定のいずれに基づくか追跡可能にする
- 自動テスト用の基準データとする
- ベンダーライブラリが更新・削除された後も利用できる資産として残す

## 責務の境界

I2CDeviceDB が正本として持つものは、再利用可能なデバイスの事実・振る舞い・根拠です。

- chip / product / library のカタログ
- 生成可能な chip profile（transport、register / command、field、operation、state、timing、conversion）
- 実験の入力・結果・環境を表す observation と、その一次証拠である raw / decoded capture
- library probe と characterization probe、および安全な宣言的シナリオ
- profile と生成物を検証するテストベクター

次は派生プロジェクトの責務とします。

- Arduino / Linux / Python / Rust など、特定言語・実行環境向けアクセスライブラリとそのランタイム
- ESP32 / RP2040 / Linux 仮想バスなど、特定 backend 向けエミュレータエンジン
- 各エコシステムへのパッケージ公開、API 設計、排他・キャッシュ・リトライなどの実行時ポリシー

判断基準は「デバイスについての中立で再利用可能な事実なら本プロジェクト、特定の実行環境でそのデータを動かす実装なら派生プロジェクト」です。スキーマが安定するまでは生成器のプロトタイプを同居させてもよいが、生成物や特定 backend の都合を chip profile の正本にはしません。

## データフロー

```text
datasheet ────────────────> chip catalog ───────────────────────────┐
       └─────────────────> curated chip profile <──────────────┐    │
library probe ────────────> observation + capture ─────────────┤    │
characterization probe ───> observation + capture ─────────────┘    │
                                                                  build
                                                                    │
                                                        integrated chip JSON
                                                                    │
                                           ┌────────────────────────┼─────────────────┐
                                           ▼                        ▼                 ▼
                              access library generator    emulator generator    conformance tests
```

既存ライブラリのキャプチャは、その実装が利用する通信経路と互換性を示す証拠です。ライブラリが使わない機能、異常系、状態遷移、時間挙動までは網羅できないため、chip profile の正本をキャプチャから無条件に自動推定しません。characterization probe で制御された入力を与え、観測結果をレビューして profile に反映します。

## Catalog-first / profile-later

chip の収録は二段階で進めます。

1. **基本カタログ** — `chips/<key>.yaml` に識別・検索・product との連結に必要な安定情報を登録する。詳細 profile がなくても有効な chip として公開できる。
2. **詳細 profile** — `profiles/<key>.yaml` に transport、register / command、field、operation、state、timing、conversion、evidence を追加する。datasheet 調査と実機 characterization を通じて段階的に深くする。

編集用ソースは分離するが、論理的には同じ chip エンティティです。ビルド時に key で結合し、サイト・生成器には chip 単位の統合 JSON を提供します。これにより、基本カタログを広く増やす作業と、少数 chip を生成可能な深さまで調査する作業を独立して進められます。

- profile は任意。存在しないことは「機能がない」ではなく「未調査」を意味する。
- catalog と profile に同じ事実を重複保存しない。識別・アドレス・datasheet は catalog、通信上の意味と振る舞いは profile を権威とする。
- profile の completeness は `coverage` で明示し、ファイルの存在だけで生成可能と判定しない。
- 公開 JSON は統合するが、生成物を編集元に戻さない。YAML が正本である。

## 想定利用者

Arduino / ESP32 / Linux 向けの I2C ライブラリ開発者、I2C デバイスエミュレータ開発者、テストツール開発者、リバースエンジニアリングを行う開発者、教育用途。

## 対象デバイス

I2C 通信を利用するすべてのデバイス。特定メーカーに依存しません。

- センサ、OLED/LCD、GPIO Expander、ADC/DAC、EEPROM、RTC、IO コントローラ など
- M5Stack Unit、Grove、Qwiic、STEMMA QT、Adafruit / SparkFun 製品、秋月電子モジュール、Generic I2C Device

**メインターゲットは M5Stack 社の Unit** です。汎用的に使えるデータを目指しつつ、当初は Unit の収録を優先します。ファーストターゲットは `m5stack-u001-c`（ENV III / SHT30 + QMP6988）。調査項目と完了条件は [pilots/m5stack-u001-c.md](pilots/m5stack-u001-c.md) を正とします。

## 基本モデル

キャプチャの同一性を次のように定義します。

> **capture = target × probe × bus_speed × condition × content_hash**
> target は基本 chip、probe は characterization scenario または library(+version)。operation は capture 内を UART マーカーで区切る検索・比較用の slice で、capture 単位のスカラではない。

- **target（対象）** — その probe が叩く対象。基本は **chip**。チップ単位に割れないユニット結合 API のライブラリの場合だけ unit になる（例外）。
- **chip（I2C デバイス）** — 型番単位の実体。汎用資産の本体。プロファイルはここに置く。**capture の既定の target**。
- **product（製品 / Unit）** — 物理的に接続する対象。**capture の identity には入らない**。「どの chip がどのアドレスに載るか」の部品表であり、「製品ビュー」（その製品の chip のデータを集約）と再現（どの製品を接続するか）のために参照される。
- **probe** — 二系統。library probe は既存実装の**呼び出し方（コードパス）単位**、characterization probe は低レベル I2C で振る舞いを確認する scenario 単位（[DATA_MODEL.ja.md](DATA_MODEL.ja.md)・[COLLECTION.ja.md](COLLECTION.ja.md)）。
- **operation** — 操作単位（初期化 / 測定 / リセット …）。API 単位ではなく操作単位で整理する。
- **bus_speed** — I2C クロック（100k / 400k / 800k …）。同じ操作を速度違いで収集する。
- **condition** — 収集条件（`nominal` / `continuous` / `tight-timing` / `overspeed` / `clock-stretch`）。仕様内の nominal と、意図的に負荷をかけた「汚いデータ」を区別する。

1 つの capture は 1 つの target（基本 chip）を対象とし、operation で区切られる。チップ軸の分析は chip ごとの capture を並べて行う。詳細は [DATA_MODEL.ja.md](DATA_MODEL.ja.md)。

## データ収集方針

通信は可能な限り実機から取得します。

```text
pytest（収集オーケストレータ）
    ├─ sigrok キャプチャ開始/停止
    └─ ESP32 Probe Firmware ── 対象デバイス（Unit / I2C デバイス）
```

ロジックアナライザで **SDA / SCL / UART（マーカー）** を同時収集します。MCU は当初 **ESP32-S3 単一** を前提とします（I2C 通信は MCU にほぼ非依存のため複数 MCU 対応は初期対象外。ただし再現に必要な環境（fqbn / platform・library version 等、後述のメタデータ）は記録する）。

収集（collection）の詳細は [COLLECTION.ja.md](COLLECTION.ja.md)。

### キャプチャのバリエーションと信頼性

同じ chip × probe × operation でも、以下の軸で複数のキャプチャを収集します。

- **バス速度 (bus_speed)**: 主対象は **100k / 400k**（800k は任意）。**対象チップの定格を超えて無理に上げない**（100k でしか動作しないデバイスもある）。
- **収集条件 (condition)**:
  - `nominal` — 仕様内の速度・タイミングでの標準的な通信。**基準参照**。
  - `continuous` — 連続 / ストリーミング取得（ポーリング間隔の話でバス速度非依存）。
  - `tight-timing` — 推奨より短い間隔でのポーリング（同上）。
  - `clock-stretch` — クロックストレッチの観測。通常速度（100k / 400k）で観測できれば十分。
  - `overspeed` — デバイス定格を超えるバス速度。**core 外・非再現の参考データ**（下記）。

`nominal` 以外は意図的に負荷をかけた「汚いデータ」で、挙動の観測が目的です。

**信頼性の位置づけ**: これらのキャプチャは配線・プルアップ抵抗値・バス容量・ケーブル長・プローブ・温度などの**物理層に依存する参考データ**であり、絶対的・保証されたデータではありません。とくに **`overspeed` は本質的に非再現**です — 通信可否はプルアップ値やバス容量で大きく変わるうえ、ロジアナを接続した時点で配線が伸びて実環境より条件が悪化する（ロジアナ有りの overspeed は実力より悲観的に出る）。そのため **バス速度は基本 400k まで**とし、overspeed はデータとして残しても「参考・非保証」と明記する。安定して参照できるのは Level5 のチップ事実や `nominal`（100k / 400k）のトランザクション内容。消費側は `condition: nominal` に絞れば最もクリーンな参照が得られます。

### 収集と検証の切り分け

一次成果物は「observation + capture」であり、実測結果を期待値に合わせた pass/fail へ変換しません。

| モード | 役割 | 判定 |
|--------|------|------|
| **収集 (collect)** | library / characterization probe で操作し、入力・結果・provenance・capture を保存 | pass/fail しない。差異が出てもそれ自体がデータ |
| **構造検証 (validate)** | キャプチャがデータとして使えるか（START/STOP、ACK/NACK デコード可、想定アドレス応答）だけ確認 | 緑/赤にしてよい。壊れたキャプチャは資産にならないため |
| **比較 (compare)** | 2 つのキャプチャの差分レポート（同一チップ × 別ライブラリ、別ロット、別 version …） | pass/fail せずレポート出力。オフラインツール |
| **整理 (curate)** | datasheet と observation を根拠に profile の規則を追加・更新 | schema / evidence の整合性をレビューする |
| **適合確認 (conformance)** | profile から生成した実装を根拠テストベクターへ照合 | 生成物に対して pass/fail してよい |

「同じ操作で同じ通信が再現するか」を強制する回帰テストは責務に含めません（実機の個体差・タイミング揺らぎと戦うことになり責務が肥大するため）。複数個体・複数ライブラリで結果が違っても、すべて収集して残します。「ライブラリによる呼び方の違いの検証」は compare の主要ユースケースです。

## UART マーカー

UART は通信内容ではなく解析補助として使います。テストケース名・操作名・実行フェーズの意味付けに利用します。

```text
CASE_BEGIN readTemperature
PHASE initialize
PHASE measurement
PHASE read
CASE_END readTemperature
```

## テストケース（操作単位の統制語彙）

収集は API 単位ではなく操作単位で整理します。マーカー名の統制語彙として、当面は以下を採用します（収集を進めながら調整）。

`Device Detection` / `Address Sweep` / `Initialization` / `Default Read` / `Configuration` / `Single Measurement` / `Continuous Measurement` / `Status Read` / `Output Control` / `Reset` / `Sleep` / `Wake` / `Error Handling`

### アドレススキャンと全アドレス取得

- **Device Detection / Address Sweep は全 7bit アドレス（0x00–0x7F, 128 個）を対象に、極力広くスキャンする。** I2C 仕様上の予約領域（0x00–0x07 / 0x78–0x7F）も含める。仕様を無視して予約アドレス（0x00 など）に応答するデバイスが実在するため。
- **presence（どのアドレスが居るか）の権威は MCU（`endTransmission` の ACK）**。同じスキャンの LA キャプチャは、浮きバスではノイズを ACK と誤読し ACK アドレスも件数も実行ごとにブレるため、**presence 判定には使わない**（実測で確定）。scan の MCU presence マップと provenance は observation として保存し、LA データは **capture として永続化しない**。詳細は [COLLECTION.ja.md](COLLECTION.ja.md)。
- 予約アドレスへのアクセスは副作用があり得る（例: 0x00 general call がデバイスをリセットする）。副作用の可能性を承知の上で行う。

## データの優先順位（Level 1〜5）

> 粒度は収集しながら調整する前提。

- **Level1 生キャプチャ** — `.sr` 等。最も信頼できるデータ。
- **Level2 デコード済み通信** — JSON / JSONL / CSV。アドレス・R/W・データ・ACK/NACK・operation / phase。絶対 timestamp は内容 identity に使わず、必要な相対時間を timing feature として保存。
- **Level3 observation / provenance** — scenario / API 入力、MCU 戻り値、外部刺激、匿名 specimen、product、取得日時、電源・bus・instrument、fqbn / platform・core / probe・library version。取得日時や specimen は capture identity に使わない。
- **Level4 意味付け** — 初期化 / 設定 / 測定 / スリープ / リセット / ステータス取得 等（UART マーカー由来）。
- **Level5 デバイスプロファイル** — transport、register / command、field、値の意味、operation、state、副作用、timing、conversion と evidence。アクセスライブラリ / エミュレータ生成器が読む正本。深さの指針は [DATA_MODEL.ja.md](DATA_MODEL.ja.md)。

## メタデータ

キャプチャは内容アドレスとし、実験の再現と差異の説明に必要な情報は参照元 observation の provenance に置く。

- **再現環境**: `sketch.yaml` 由来の fqbn、platform / core version、probe / library version（arduino-cli が解決した実際の版）。
- **収集パラメータ**: バス速度・収集条件（これらは identity にも含まれる）。
- **実験 provenance**: 匿名 specimen ID、product、取得日時、電源、pull-up、配線、周囲条件、instrument と sample rate。関係する項目だけ必須化する。
- **制御された入出力**: scenario / API 引数、MCU 戻り値、外部刺激、基準計の値。
- デバイス名・メーカー・センサ IC・I2C アドレスは chip / product / library の参照から導出する（重複保存しない）。

capture の識別は日付や specimen ではなく**内容ハッシュ**（[DATA_MODEL.ja.md](DATA_MODEL.ja.md)）。provenance を保持することと、identity に含めないことを区別する。

## データ形式

人間とプログラムの両方が扱いやすい形式を採用します。優先形式は JSON / JSONL / YAML / Markdown。CSV は互換性維持のため補助的に利用します。

## 解析ツール

`tools/` に以下を含めることを想定します: sigrok データ変換 / UART マーカー解析 / I2C トランザクション生成 / デバイスプロファイル生成 / データ整合性チェック / データ比較 / キャプチャ可視化。

## ライセンスと収録対象

コードとドキュメントは MIT License（[LICENSE](../LICENSE)）。収録するデータは再配布可能なもののみとします。

- 収録対象: 自身で取得した通信データ / オープンソースライブラリから取得した通信 / 公開仕様書から確認可能な情報。
- 著作権上問題のある資料や再配布できないデータは収録しません。

## 設計方針

ベンダー・MCU・ライブラリに依存しない。再現可能なデータを保存する。機械処理しやすく人間にも理解しやすい構成とする。将来的な拡張を前提とし、下位互換性を可能な限り維持する。

## 派生プロジェクト

I2CDeviceDB を利用して、汎用 / ESP32 / Arduino / Linux 向け I2C ライブラリ、I2C デバイスエミュレータ、仮想 / モックデバイス、テストツール、プロトコル解析ツール、ドキュメント自動生成ツールなどを開発しやすくすることを目指します。
