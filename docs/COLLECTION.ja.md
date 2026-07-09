# 収集設計（collection）

> ステータス: 叩き台。方針は確定、実装はこれから。パケットキャプチャの具体実装（sigrok の叩き方・pytest との同期）は最初に conftest.py で育てる。

## 全体像

```text
collection/ (uv + pytest)
    ├─ sigrok キャプチャ開始
    ├─ probe firmware を書き込み・実行（pytest-embedded + arduino-cli）
    │      └─ 対象デバイス（Unit / I2C デバイス）を実際に叩き、UART マーカーを出力
    ├─ UART マーカー / serial ログを収集
    ├─ sigrok キャプチャ停止 → captures/raw/ に保存
    └─ メタデータ付与（再現環境のみ: fqbn / platform・library version。日付・個体は持たない）
```

`collection/` は uv プロジェクトのルート（`pyproject.toml` / `.env` / `conftest.py`）で、probe（スケッチ）を配下に同居させる（ESP32KeyBridge の `tests/` と同じ流儀。pass/fail テストではなく収集なので `collection`）。

pytest は **pass/fail の判定器ではなく収集オーケストレータ** として使う。fixture・パラメータ化・ハードウェア紐付けを活用し、成果物はキャプチャ + メタデータ。緑/赤にするのは構造検証（validate）だけ（[SPEC.ja.md](SPEC.ja.md) 参照）。

## ハードウェア構成

- MCU: **ESP32-S3 単一**。
- ロジックアナライザ: sigrok 対応機で **SDA / SCL / UART（マーカー）** を同時収集。
- 対象: M5Stack Unit（Grove コネクタ）をファーストに、汎用 I2C デバイスへ拡張。
- 全部を全自動では動かさない。**対象デバイスを接続してから収集ランを実行**する運用（接続機は常時接続前提にしない）。

## パケットキャプチャの実装方針

キャプチャ制御（sigrok 起動/停止のタイミング、UART マーカーとの同期、メタデータ付与、出力パス命名）は **まず `collection/conftest.py` の fixture として育てる**。

- 理由: 外部プラグインの都合に縛られる前に、このプロジェクト内で自由に API をイテレーションできる。
- 使い方が枯れて他プロジェクトでも再利用したくなったら、fixture の実装を `pytest-embedded-arduino-cli` 等の plugin hook へ移植する。

`pytest-embedded` の arduino-cli / serial プラグインで probe の書き込みと serial マーカー取得を行い、sigrok は当面 `sigrok-cli`（システム版 `/usr/bin/sigrok-cli`。AppImage は使わない）を subprocess から叩く。キャプチャ backend は **sigrok-cli 一本**に固定する（libsigrok バインディング等へは広げない）。

### 窓の制御（`--continuous` + SIGINT）

固定 `--time` は「sketch の実行タイミングとの競合」「無駄録り」になるため使わない。**pytest がマーカー駆動で窓を制御**する:

1. probe を書き込み、**`READY` をポーリングして起動確認**（下記）。
2. conftest が `sigrok-cli … --continuous -o <staging>/capture.sr` を subprocess で起動し arm を待つ。
3. probe へ `RUN` コマンドを送り、対象 operation（初期化含む）を走らせる。
4. `pytest-embedded` の serial で終端 sentinel（`ALL_DONE` / 最後の `CASE_END`）を待つ。
5. sigrok プロセスへ **SIGINT** を送りクリーン停止・`.sr` フラッシュ。

窓が run にぴったり張り付き、ハードウェアトリガは不要。fx2lafw は `continuous: on` 対応を確認済み。

**sigrok の stdin は tty で（実測の要注意点）**: `sigrok-cli --continuous` は **stdin が tty のときだけ**走り続け、非 tty / EOF（`-s` 無しの pytest fd キャプチャ下の `/dev/null` や `DEVNULL`）だと即 `rc=0` で終了する。conftest は sigrok に **疑似端末（pty）を stdin として与え master を開いたまま保持**（EOF を起こさない）、stdout/stderr はログファイルへ、`start_new_session` で pytest の端末から分離する。

**起動タイミングの2つの落とし穴**（実測で判明）:

- **boot ログの取りこぼし**: boot 時の一発 `READY` はシリアルを開く前に出ると失われる。初期化に時間がかかる probe だとなおさら。→ 受動待ちをやめ、**pytest 側から `READY` を能動ポーリング**して起動を確認する（probe は loop() で `READY` コマンドに再応答する）。
- **キャプチャ対象の通信は必ず `RUN` 後に出す**。sigrok を arm する前（＝ `setup()` や init）に出た I2C 通信は窓の外になり取りこぼす。ライブラリの `begin()` 等の初期化通信も**捕りたいなら `RUN` ハンドラ内で実行**し、`setup()` ではバス通信を発生させない（ピン設定のみ）。

### sigrok の設定は `.env` から

装置・配線は環境依存なので `.env` を正とし、conftest が組み立てる（[「`.env` とポート」](#env-とポート)）。

- `SIGROK_DRIVER` を指定。`SIGROK_CONN` は**空なら sigrok-cli にも渡さない**（自動選択もしない）。`--scan` は「demo を除外し、指定ドライバの存在を検証」にだけ使う。
- チャネルは **信号ごとの個別ラベル**（`SIGROK_CH_SDA=D2` 等）で持ち、probe が要求する信号だけ抜き出して `--channels D0=UART_TX,D1=SCL,D2=SDA` を**実行時合成**する（複合キーを 1 変数に書かない → 他試験と共有可能）。以降 `.sr` は信号名でラベルされ、decode も `-P i2c:scl=SCL:sda=SDA` と**信号名で叩く**。物理 `Dn` 割当は capture の一瞬だけの関心事で、`.sr` 以降・内容ハッシュは配線非依存。

## Probe アーキテクチャ

probe は **(target × library)** 単位。target は基本 chip で、**product は probe に出ない**。命名だけ確定で、フォルダ実体は未作成。

### アドレススキャン probe（presence 発見・検証。最初・全製品共通）

生 Wire だけで全アドレスを舐め、**どのアドレスにデバイスが居るか（presence）**を調べる（= Device Detection / Address Sweep）。scan の産物は presence マップで、**capture データとしては永続化しない**（下記）。

- ライブラリを一切 include しない → Wire 競合と無縁。製品非依存で **1 スケッチを全製品で使い回す**。
- **全 7bit アドレス 0x00–0x7F（128 個）を極力広くスキャン**する。I2C 予約領域（0x00–0x07 / 0x78–0x7F）も含める（仕様を無視して予約アドレスに応答するデバイスが実在するため）。
- 予約アドレスへのアクセスは副作用があり得る（例: 0x00 general call がデバイスをリセット）。承知の上で行う。
- 速度で presence はほぼ変わらないので nominal 1 本でよい。

**presence の真実は MCU（実測で確定）**:

- presence は **MCU の `Wire.endTransmission()`（0 = ACK = present）が権威**。MCU は 9 クロック目の SDA LOW で ACK 判定するので、デバイス無し＋プルアップ無しの浮きバスでは正しく全 NACK（0 件）になる。
- **同じ scan の LA キャプチャは presence 判定に使わない**。浮きバスでは LA デコーダがノイズを ACK と誤読し、ACK アドレスも decoded transaction 件数（例 128↔120）も**実行ごとに不安定**。LA データは実ユニット来訪までの参考／統一パイプラインの副産物として `_staging` に残すだけで**非永続**。
- MCU は presence を **USB 制御シリアル**へ `FOUND 0xNN`（末尾 `ALL_DONE found=N`）で出す。CASE マーカーは従来どおり LA 観測線 `Serial1`。pytest が `FOUND` を集めて presence マップ化する。
- **ゲート**: MCU の presence が 0 件なら scan は失敗させて止める（居ないデバイスに chip probe を回しても無意味）。chip probe 側も各自 `RUN` 冒頭で対象アドレスの presence を自己チェックする想定（scan 非依存）。

### ライブラリ probe：分ける単位は「呼び出し方（コードパス）」

**1 probe = 1 つの呼び出し方**。呼び出し方（API・クラス・シーケンス）が違えば別 probe、同じならまとめてターゲット（アドレス等）をパラメータ化。精度・出力の差だけで呼び出しが同じなら分けない。多くのライブラリはチップ単位に割れるので **probe = `(chip × library)`**。

- **複数ライブラリを 1 スケッチに同居させない**（各ライブラリが `Wire.begin()` / `setClock()` を取り合うため）。1 probe 1 ライブラリなら競合は「probe vs そのライブラリ 1 つ」だけ。
- **命名 = `<chip>__<library>`**（chip 先頭でチップごとに並ぶ）。M5Unit-ENV のようにセンサ別クラスを持つライブラリも、BMP280 用 / DHT12 用に分割し当該チップを含む全製品で再利用（product は名前に出ない）。
- **例外**: チップ単位に割れず 1 呼び出しでユニット全体を叩く結合 API のライブラリだけ `<unit>__<library>`。
- アドレス（0x76/0x77 等）は実行時パラメータ（product の component から渡す）。同じチップが別アドレスでも probe は分けない。
- 1 回の書き込み＝1 回の sigrok 連続キャプチャを基本とし、`CASE_BEGIN <operation> / PHASE ... / CASE_END <operation>` で operation を区切る（速度・条件で分ける場合は別テスト／別キャプチャにしてよい）。
- 数は増えても**共通テンプレート**（マーカー出力・速度設定・操作列）に沿わせ、差分はライブラリ固有の呼び出しだけにする。

### probe（スケッチ）と pytest テストの関係

COLLECTION が規定するのは **probe の識別と命名まで**。テストの切り出し方は規定しない。

- **probe = 1 つの Arduino スケッチ**（`<chip>__<library>`。arduino-cli の都合でフォルダになる。library は repo 由来 slug）。
- **駆動は pytest のテスト**（スケッチを書き込み・実行し、sigrok でキャプチャ）。**どの範囲を 1 テストにするか（1 probe 1 テスト / 複数テストに分割 / operation・speed・condition で parametrize）は pytest 実装の裁量**で、テストファイルは自由に分割してよい。

配置は一例（固定しない）:

```text
collection/                          # uv プロジェクトルート
  pyproject.toml / uv.lock / .env
  conftest.py                        # sigrok・UART マーカーの fixture
  sketches/                          # probe = (chip × library) ごとの Arduino スケッチ
    scan/
      scan.ino
      sketch.yaml                    # profile / fqbn / platform / library
      build_config.toml              # .env → コンパイル時 define のマップ
    bmp280__m5stack-m5unit-env/
    bmp280__adafruit-bmp280-library/
    dht12__m5stack-m5unit-env/
    dht12__robtillaart-dht12/
  <test_*.py>                        # probe を駆動する pytest テスト（切り出しは自由）
```

### GPIO・ポートを `.env` から注入

GPIO（SDA / SCL / マーカー UART TX）は環境依存なので**スケッチに固定しない**。ESP32IRPulseKit の `tests/hardware/link_smoke` と同じ流儀を採る:

- probe ごとの **`build_config.toml` の `[defines]`** が `.env 変数名 → スケッチの #define 名` を宣言し、arduino-cli プラグインがコンパイル時 define として注入する。
- スケッチは `#ifndef` フォールバック＋`atoi()` で受ける（define は string で渡る）。

```toml
# sketches/<probe>/build_config.toml
[defines]
TEST_I2C_SDA = "I2C_SDA_PIN"
TEST_I2C_SCL = "I2C_SCL_PIN"
TEST_UART_TX = "MARKER_UART_TX_PIN"
```

```cpp
#ifndef I2C_SDA_PIN
#define I2C_SDA_PIN "8"
#endif
// I2C_SCL_PIN / MARKER_UART_TX_PIN も同様
Wire.begin(atoi(I2C_SDA_PIN), atoi(I2C_SCL_PIN));
Serial1.begin(115200, SERIAL_8N1, -1, atoi(MARKER_UART_TX_PIN));  // マーカー出力
```

シリアルポートは `pytest-embedded` の profile 名（`sketch.yaml` の profile）由来で `.env` の `TEST_SERIAL_PORT_<PROFILE>` に置く（[「`.env` とポート」](#env-とポート)）。

### 実行：製品を指定して probe セットを導出

「どの probe を回すか」は**製品から導出**する。手書きのコマンド表や per-product `.sh` は作らない（`components × supports` の二重管理・ドリフトになるため）。

- 呼び出しは**製品をパラメータ**にする。`--product`（conftest.py 実装）が `products/<key>.yaml` の `components` と `libraries/*.yaml` の `supports.chips` から probe セット（**scan ＋ 各 chip × 対応 library**）を計算し、該当テストだけ選択する。
- 各テストは自分の probe key（`<chip>__<library>` / `scan`）を marker 等で宣言 → 選択が突き合わせできる（テストの切り出し方は自由なまま）。

```sh
# U001 の probe 一式（scan ＋ dht12/bmp280 × 対応ライブラリ）を導出して実行
uv run --env-file .env pytest --product m5stack-u001
```

- **`--product` は任意フィルタ**。無指定なら通常の pytest 選択がそのまま走る（全収集、またはパス指定 `pytest sketches/scan` や `-k`）。製品でまとめて回したいときだけ付ける。
- 単一 probe や部分実行は pytest 通常のテスト選択（`-k` / node id / パス）でよい。
- 「その製品で何が回るか」は同じ導出を `--collect-only` 等で確認できる。
- この導出は「カバレッジは product × 選定基準 と実データの突き合わせで導出」（後述）と同じロジックの再利用。

### Wire 初期化の扱い

1 probe 1 ライブラリなので、競合は自分の probe とそのライブラリの間だけ。手順：

1. `Wire.begin()` + `Wire.setClock(target)` で目標速度を設定。
2. `lib.begin()`（可能なら `TwoWire&` / pins / clock を渡せるライブラリはそれを使う）。
3. begin 後に **もう一度 `Wire.setClock(target)` を上書き**（begin で clock を戻すライブラリ対策）。

どうしても clock を固定してくるライブラリは、その速度バリアントが取れない**制約として記録**する（無理に戦わない）。ライブラリ固有の癖は各スケッチの notes に残す。

## キャプチャの scope・収集・表示

- **全 probe は同一パイプライン**（flash → LA 取得 → decode）。probe を系統で分けない。**差は永続化のみ**: scan（presence）は非永続、chip probe（byte 列）は `captures/` へ永続。
- **capture は既定 chip-scoped**（target = chip）。通信はチップ + ライブラリ + 設定で決まり製品非依存（違いはアドレスバイト程度で導出可能）。その chip を含むどの製品でも使い回す。メタデータは再現環境のみ（日付・個体は持たない）。ユニット結合 API の例外ライブラリのみ unit-scoped。
- **収集は無制限**。過去データがあっても再取得してよい。全部残す（差異もデータ）。
- **絞るのは表示（display）側**。論理キー `(target × library × operation × speed × condition)` でグループ化し、一致していれば**代表を 1 つだけ**見せ、食い違うときだけ「ここが違う」を強調する（[SITE.ja.md](SITE.ja.md)）。差異軸はライブラリ版・速度・条件・内容（日付・個体は持たない）。
- 「この製品のこの chip は既存データでカバー済み」というカバレッジは、product × 選定基準 と実データの突き合わせで**導出**する。

## バス速度・収集条件のバリエーション

`bus_speed`（主対象 100k / 400k、800k は任意）と `condition`（nominal / continuous / tight-timing / clock-stretch / overspeed）は**キャプチャ単位のスカラ**とし、1 キャプチャ = 1 速度 1 条件で保存する（メタデータ・compare を単純に保つため）。

- collection（pytest）がこれらをパラメータ化し、**組み合わせごとに別キャプチャ**を出す。
- probe は目標の速度・条件を受け取る（compile flag か serial コマンド）。速度は `Wire.setClock()` 等で設定。
- **対象チップの定格を超えて上げない**（100k でしか動かないデバイスもある）。`overspeed` は core 外・非再現の参考データ（ロジアナ接続で配線が伸び実力より悲観的に出る。[SPEC.ja.md](SPEC.ja.md)）。
- `nominal` 以外は意図的な負荷（汚いデータ）。挙動は物理層依存の**参考データ**である旨は [SPEC.ja.md](SPEC.ja.md) を参照。

### ロジアナのサンプルレート

- **既定 8MHz 固定**（`.env` の `SIGROK_SAMPLERATE` で上書き可）。安価な ≤24MHz ロジアナ（fx2lafw 系）でも確実に張り付く帯域（8ch × 8MHz = 8 MB/s で USB2 に余裕）で、かつ 100k→80× / 400k→20× / 800k→10× と core 全域でオーバーサンプリング比 ≥10× を確保できるため。プロトコルデコードの目安は最低 ~5×・快適 ~10×。
- 24MHz は fx2lafw の実効上限付近でサンプルドロップの恐れがあり、**再現性を損なうため既定にしない**。overspeed を攻める場合のみ明示的に上げる（忠実度に上限あり）。
- samplerate は `.sr` の時間精度にしか影響せず、**decoded 内容・内容ハッシュには無関係なので保存しない**（bus_speed と固定ルールから導出）。

## UART マーカー規約

```text
CASE_BEGIN Initialization
PHASE reset
PHASE configure
CASE_END Initialization
```

- `CASE_*` の名前は [SPEC.ja.md](SPEC.ja.md) の操作単位統制語彙を使う。
- マーカーは通信内容ではなく意味付け（Level4）に使う。decoded transaction にマーカー文脈（operation, phase）を付与する。

## デコードと保存

1. sigrok の生キャプチャ → staging に保存（Level1 raw `.sr`。**永続**）。
2. `sigrok-cli -P uart -P i2c --protocol-decoder-jsontrace` で decode（i2c と uart が**共通タイムベース**の Google Trace 形式で出る。この共通軸が Level4 相関の要）。**jsontrace は中間生成物で保存しない**（`.sr` から毎回作り直せる。bit 単位で冗長）。
3. `tools/` のデコーダが jsontrace を圧縮: I2C の bit/byte イベント → transaction 列（各行 address / rw / data / ack、Level2）、UART の 1 文字 → 行テキスト。
4. UART マーカー行（`CASE_*` / `PHASE`）を timestamp で突き合わせ、各 transaction に operation / phase を付与（Level4）→ compact な `decoded.jsonl`（**永続**、数 KB）。
5. 再現メタデータ（Level3: fqbn / platform・library version）を添付。日付は付けない。
6. decoded 内容のハッシュで命名し（[DATA_MODEL.ja.md](DATA_MODEL.ja.md)）、validate 通過分を `captures/` へ。同一内容は同名で自然に畳まれる。

- decode はハーネスに統合済み（`cap.decode()` が `tools/decode.py` で `_staging/<name>.jsonl` を生成）。`_staging` は**実行開始時にワイプ**する一時置き場（実行直後は残る）で、永続ストアは `captures/`。
- **scan の decoded は永続化しない**（presence は非 capture データ。前述「presence の真実は MCU」）。永続対象は chip probe の byte 列だけ。
- decoded は絶対 timestamp を持たない（identity・内容ハッシュに含めない。timing 系 condition のみタイミング特徴を後で足す）。

## 検証（validate）の範囲

- START/STOP が揃っているか、ACK/NACK がデコードできるか、想定アドレスに応答があるか、などデータの健全性のみ。
- 通信内容の一致（回帰）は判定しない。差異は compare（オフライン）でレポートする。

## `.env` とポート

装置・配線・ポートは環境依存なので `.env` を正とし、conftest が読み取って sigrok コマンドと probe の define を組み立てる。ESP32IRPulseKit の `tests/.env.example` と同じ流儀（`TEST_*` 前缀、profile 名由来のポート）。

```dotenv
# serial（profile = sketch.yaml の profile 名）
TEST_SERIAL_PORT_ESP32S3=/dev/ttyUSB0
# probe GPIO（build_config.toml 経由で define 注入）
TEST_I2C_SDA=8
TEST_I2C_SCL=9
TEST_UART_TX=3
# host / capture（sigrok）
SIGROK_DRIVER=fx2lafw
SIGROK_CONN=              # 空なら sigrok-cli に conn を渡さない
SIGROK_SAMPLERATE=8MHz    # 既定 8MHz。保存しない（時間精度のみ）
SIGROK_CH_UART_TX=D0      # 信号ごと個別ラベル。使う信号だけ実行時合成
SIGROK_CH_SCL=D1
SIGROK_CH_SDA=D2
```

具体名（ポート・GPIO・conn）は実行環境ごとに `.env` で確定する。`.env.example` を用意する。
