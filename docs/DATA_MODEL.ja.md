# データモデル

> ステータス: 叩き台。カタログのキー方針と「profile / observation / capture」の責務分離は確定。behavior profile のフィールドは BMP280 / DHT12 の characterization を通して追加・調整する。

## エンティティ

| エンティティ | 例 | 役割 | 再利用性 |
|--------------|-----|------|----------|
| **chip catalog** | `chips/bmp280.yaml` | 識別・検索・product 連結のための基本情報。profile がなくても登録・公開できる | 高（多製品で共通） |
| **chip profile** | `profiles/bmp280.yaml` | transport とデバイスの行動仕様。**アクセスライブラリ / エミュレータ生成器が読む正本** | 高（多製品で共通） |
| **product** | `m5stack-u001` | 部品表: どの chip がどのアドレスに載るか + コネクタ・ベンダー・URL。**capture の identity には入らない**（provenance と集約ビュー用） | 中 |
| **library** | `m5stack-m5unit-env` | 収集に使った実装。repo・対応 chip（実行版は observation provenance で pin） | — |
| **scenario** | `bmp280/forced-measurement` | characterization で実行する制御された入力と手順。可能な限り共通 DSL で宣言 | 高 |
| **observation** | ある実験 run | scenario / library probe の入力、結果、環境、specimen、capture 参照を束ねる実験記録 | — |
| **capture** | ある observation のバス記録 | raw 波形と decoded transaction。profile の一次証拠・互換性テストベクター | — |

catalog / profile / observation / capture の役割を混ぜないことをデータモデルの中心原則とする。

- **chip catalog は何者か**を表し、広く先行登録できる。
- **chip profile はどう通信し、どう振る舞うか**を表し、後から段階的に深くする。
- **capture は起きた通信**であり、観測していない振る舞いを主張しない。
- **observation は何を与え、何が起きたか**を再現可能に記録する。成功を期待値として書き換えず、差異も残す。
- **chip profile は複数の根拠をレビューして一般化した規則**であり、アクセスライブラリ / エミュレータ生成器の入力となる。

## キー設計（確定）

- **product キー = `slug(vendor)-slug(sku)`（フラット）。** 例 `m5stack-u001`。中身のチップが変われば SKU が変わる（ENV = U001 / ENV II = 別 SKU …）ので SKU をキーに含める。library の `slug(owner)-slug(repo)` と同型。
- **chip キー = 型番 slug（vendor 無し）。** `bmp280`, `dht12`。部品型番はほぼグローバル識別子なので vendor で名前空間化しない（product・library は SKU/repo 名が vendor 間で衝突しうるため prefix を付ける）。BMP280 と BME280、リビジョン差など挙動が異なるものは原則別エントリ。
- **library キー = repo 由来の slug（判断の余地なく一意）。** `key = slug(owner)-slug(repo)`（`slug()` は小文字化し英数字以外の連続を `-` に置換）。ただし `slug(repo)` が `slug(owner)-` で始まる場合は `slug(repo)` のみ（owner 重複回避）。owner を含むので同名衝突（DHT12 の RobTillaart 版 / xreef 版）も区別できる。
  - 例: `m5stack/M5Unit-ENV` → `m5stack-m5unit-env` / `adafruit/Adafruit_BMP280_Library` → `adafruit-bmp280-library` / `RobTillaart/DHT12` → `robtillaart-dht12`。

## 連結

```text
product ──references──> chip     （どの chip がどのアドレスに載るか = 部品表）
profile ──describes───> chip     （同じ key の詳細行動仕様。0 または 1）
scenario ──targets────> chip      （何を確認する実験か）
observation ─target───> chip      （制御された入力・結果・provenance）
observation ─uses─────> scenario  （characterization の場合）
observation ─uses─────> library   （library probe の場合、version 付き）
observation ─has──────> capture   （0 個以上の一次証拠）
capture  ──target────> chip       （その capture が叩いた対象。既定は chip）
library  ──supports──> chip      （そのライブラリが叩けるチップ）
chip profile ─evidence> observation / datasheet（規則ごとの根拠）
```

- `chips/<key>.yaml` は必須、`profiles/<key>.yaml` は任意。同じ key で結合し、profile だけが孤立することは許さない。
- profile が存在しない場合は `unknown / not-characterized` であり、その chip に機能が存在しないことを意味しない。
- observation は `kind: characterization | library` を持つ。library は library observation でのみ必須で、characterization の identity を特定ライブラリに依存させない。
- capture の論理キーは `target × probe × bus_speed × condition` と decoded content hash。`probe` は scenario または library(+version)。operation は capture 内の slice であり、product とともに identity には入らない。
- product は再現（接続する製品）と集約ビュー（「この製品のチップのデータ」）のために参照されるだけ。
- chip 側は「取りうるアドレス一覧（アドレスピンで可変）」、product 側は「実際に使われた確定アドレス」を持つ。probe は実行時にそのアドレスをパラメータで受け取る。

## probe の二系統

### library probe（呼び出し方＝コードパス単位）

probe は「あるライブラリの、ある呼び出し方が叩く対象」で分ける。**分類（製品単位/チップ単位）ではなく、呼び出し方（API・クラス・シーケンス）が違うかどうか**が基準。

- 呼び出し方が違えば別 probe。同じならまとめてターゲット（アドレス等）をパラメータ化。精度・出力の差だけで呼び出しが同じなら分けない。
- 多くのライブラリは**チップ単位に割れる**（例: M5Unit-ENV はセンサ別クラスを持つ → BMP280 用と DHT12 用に分割でき、どちらも当該チップを含む全製品で再利用）。→ probe = `(chip × library)`、product は名前に出ない。
- **例外**: チップ単位に割れず、1 呼び出しでユニット全体を叩く結合 API のライブラリだけ target=unit になる（`(unit × library)`）。この場合のみ product/unit が出る。

probe の実体・命名・フォルダは [COLLECTION.ja.md](COLLECTION.ja.md)。

### characterization probe（確認項目＝scenario 単位）

既存ライブラリを介さず、低レベル I2C primitive でデバイスの振る舞いを確認する。共通操作は宣言的 scenario と共通 runner で表し、DSL で表せない処理だけ最小の chip adapter を許可する。

- reset / power-on default、safe read、write-readback、状態遷移、single / continuous operation、sleep / wake、timing、異常アクセスを対象とする。
- 全レジスタ・全値への無差別な read / write は行わない。副作用と安全範囲を profile / datasheet で確認した scenario だけ実行する。
- 外部刺激が必要なセンサは、scenario input に基準温度・湿度・圧力・電圧等を記録し、I2C 値との対応を observation に残す。
- characterization の結果は profile 候補を生成できるが、自動的に正本へ昇格させない。複数根拠を確認してレビューする。

## capture の同一性と派生軸

```text
capture = target × probe × bus_speed × condition × content_hash
              │       │          │           │            └─ decoded の意味内容
              │       │          │           └─ nominal / continuous / tight-timing / overspeed / clock-stretch
              │       │          └─ 100k / 400k / 800k …
              │       └─ scenario、または library(+version) のコードパス
              └─ 基本 chip（例外的に unit）

operation / phase = UART マーカーで capture 内を区切る slice
```

**capture は内容で識別する（コンテンツアドレス）。** identity = 論理キー `(target × probe × speed × condition)` ＋ **decoded 内容のハッシュ**。specimen・product は identity に使わない。内容が同じキャプチャは同じ名前に畳め、内容が違えば意味ある variant として残る。一方、匿名 `specimen_id`・product・実験環境・収集ツール世代は observation の provenance として保持し、個体差や再現条件を失わない。

- ハッシュ対象は **decoded の意味内容**（addr/rw/data/ack と operation/phase）。raw はハード実機で毎回タイミングが違うのでハッシュ対象にしない → `nominal` の完全一致が畳める。
- timing 系 condition（clock-stretch / overspeed / tight-timing）はタイミングが主目的なので、ハッシュ対象にタイミング特徴も含める。
- speed / condition は論理キーに残す（内容が同じでも「400k での結果 / 100k での結果」は別の知見として保持）。

`bus_speed` / `condition` はキャプチャ単位のスカラ（1 キャプチャ = 1 速度 1 条件）。`nominal` 以外は環境依存の参考データ（[SPEC.ja.md](SPEC.ja.md) の信頼性の位置づけ）。1 つの capture は 1 つの target（基本 chip）を対象とし、operation でスライスされる。チップ軸の分析は chip ごとの capture を並べて行う。

### compare の代表例

- **チップ軸（ライブラリ差）**: `chip=bmp280, operation=Initialization, bus_speed=400k, condition=nominal` を library 横断で diff → 初期化レジスタ書き込みの違いを可視化（U001 なら `M5Unit-ENV ↔ Adafruit_BMP280`）。← パイプライン検証の最初の具体ターゲット。
- **速度軸**: 同一 library / operation を `100k ↔ 400k ↔ 800k` で比較 → 速度依存の挙動差。
- **条件軸**: `nominal ↔ overspeed` / `nominal ↔ clock-stretch` で異常時の挙動を観察。

## マスタ形式の原則

- **データファイルにコメント（`#`）は書かない。** フィールドの意味・スキーマの説明はこのドキュメントに集約する。ファイル固有の内容は `notes:` フィールド（データ）に入れる。
- 一般のエンティティは 1 YAML とするが、**chip だけは基本 catalog と詳細 profile の 2 ソース**を許可する。これは同じ事実の二重管理ではなく、安定度と作業速度が異なる責務の分離である。
- catalog と profile は同じ key / ファイル stem で対応させる（`chips/bmp280.yaml` + `profiles/bmp280.yaml`）。profile に name、manufacturer、addresses、datasheets 等を再掲しない。
- **YAML が編集用マスタ、統合 JSON はビルド生成**。サイトと downstream は `chip catalog + profile` を結合した chip 単位の JSON を fetch する。生成 JSON は YAML へ逆同期しない。
- catalog schema と profile schema は別々に versioning できるようにする。ファイルには schema version を持たせ、profile の進化で基本カタログを一斉変更しなくて済むようにする。
- 生成物（JSON / HTML）は main に置かず、サイトは gh-pages ブランチへ公開する（[SITE.ja.md](SITE.ja.md)）。

### 権威と重複禁止

| 情報 | 権威 |
|------|------|
| key、型番、メーカー、検索タグ | `chips/<key>.yaml` |
| 取りうる I2C address と選択条件 | `chips/<key>.yaml` |
| datasheet / reference の一覧と ID | `chips/<key>.yaml` |
| transport、register / command / frame | `profiles/<key>.yaml` |
| field、operation、state、副作用、timing、conversion | `profiles/<key>.yaml` |
| 実験入力・結果・環境 | `observations/` |
| 実際のバス通信 | `captures/` |

ビルド時に、profile の対応 chip、key / stem、一意性、evidence / reference、scenario / observation 参照を検証する。重複フィールドを「片方が優先」で解決せず、schema error とする。

## ディレクトリと最小スキーマ

### chips/

```text
chips/<chip>.yaml   # key, name（= 型番 part number）, manufacturer, tags, addresses: [{addr, note?}],
                    # datasheets: [{id?, source, vendor?, url, revision?, date?}], notes
```

基本カタログは識別・検索・product との連結に必要な安定情報に限定する。詳細 profile がなくても chip YAML 単独で schema valid とし、一覧・product view・収録候補管理に利用できる。

```yaml
schema_version: 1
key: bmp280
name: BMP280
manufacturer: Bosch Sensortec
tags: [pressure, temperature]
addresses: []
datasheets: []
```

### profiles/

```text
profiles/<chip>.yaml   # schema_version, chip, coverage, transport, registers / commands / frames,
                       # operations, states, timing, conversions
```

profile は任意だが、存在する場合は対応する `chips/<chip>.yaml` を必須とする。基本情報を繰り返さず `chip: <key>` だけで参照する。

```yaml
schema_version: 1
chip: bmp280
coverage:
  status: partial
transport: {}
registers: []
commands: []
frames: []
operations: []
states: []
timing: []
conversions: []
```

### chip profile の深さ

**アクセスライブラリとエミュレータを生成できる、デバイス中立な行動仕様まで書く。データシート本文の複製ではなく、実装に必要な事実を構造化する。**

- `transport`: register address 幅、byte order、repeated START、auto increment、CRC / PEC 等。
- `registers` / `commands`: address / opcode、幅、`ro` / `rw` / `wo`、reset 値、writable mask、volatile、read / write の副作用。
- `fields`: bit 位置、型、enum、範囲、単位、scale、予約値。生成器が型付き API と read-modify-write を作れる粒度。
- `operations`: initialization、measurement、reset、sleep / wake 等の前提条件、手順、結果。
- `states`: mode、許可遷移、busy / data-ready、遷移を起こす write / command / 時間経過。
- `timing`: 起動・変換・更新・settling・clock stretch 等。固定値だけでなく条件式や実測分布を許容する。
- `conversions`: raw 値と物理量の変換、符号、endianness、校正係数、checksum。
- **アドレス範囲を `"0xF7..0xFC"` のような非パース文字列で書かない**。`addr: "0xF7", len: 6` のように機械可読にする。
- capture から observed sequence / known response を抽出してよいが、それだけから一般規則を確定しない。profile の operation / state はレビュー済みの正規化仕様として保存する。
- 最初から全機能を埋めることは要求しない。`coverage` / evidence により unknown と確認済みを区別し、characterization を進めながら育てる。

profile 内の主張には、可能な粒度で根拠を付ける。

```yaml
evidence:
  source: observed
  observations: [bmp280-forced-measurement-001]
  confidence: confirmed
```

`source` は `datasheet` / `observed` / `inferred`。`inferred` は生成器が既定で採用してよい保証事項として扱わず、`tentative` / `confirmed` / `variant` 等の confidence と併用する。profile から observation / capture への参照を持ち、逆引きリストはビルド時に導出する。

### 深掘りの段階

profile は一度に完成させず、次の順で育てる。

1. **cataloged** — `chips/<key>.yaml` のみ。製品との連結と資料の所在が分かる。
2. **protocol-known** — transport と register / command / frame の骨格がある。
3. **characterized** — field、副作用、state、timing、conversion が observation で裏付けられている。
4. **generator-ready** — 対象機能の coverage が明示され、schema / evidence / conformance test を通る。

`coverage.status` はファイル全体の目安にすぎない。機能ごとの known / unknown / unsupported と evidence を併記し、`generator-ready` でも未対象機能を隠さない。

### 既存 chip YAML の移行

現在の `chips/*.yaml` にある `registers` は、基本カタログ作成時に得られたデコード凡例 / seed facts と位置づける。移行期間中は読み込みを許容するが、新しい最終配置は `profiles/<key>.yaml` とする。

- profile 着手時に seed facts を検証し、`registers` または `commands` として profile へ**移動**する。コピーして両方に残さない。
- `desc` / `notes` に埋まった access、ID 値、reset opcode、byte order、CRC、address 変更、副作用等は構造化して profile へ移す。
- 移行前の `registers` があることを「profile 作成済み」「生成可能」とは判定しない。
- 現在の schema version 未記載ファイルは legacy catalog（暗黙の version 0）として扱う。catalog / profile schema 確定時に明示 version へ一括移行する。
- 全 catalog の一括移行を profile 開始の条件にしない。深掘り対象 chip から順に移行する。

### chip catalog の補足フィールド

`tags` は検索用の配列（例 `[temperature, humidity]`）。「何を測るか」はチップ固有の性質なのでここに正規化して持つ（product では持たない）。

`datasheets` は出所付きの配列。`source` で公式か否かを常に明示する：

- `manufacturer` … チップメーカー公式（= 正）。
- `vendor` … 製品ベンダーの再配布コピー（`vendor:` に誰か。例 `m5stack`）。公式より古い版のことがある。
- `reseller` … 部品販売サイト（LCSC 等）由来。

`revision` / `date` で版を記録し、公式と提供元コピーの版差が分かるようにする。公式が存在しない場合も誤リンク（公式を騙る）は張らず、必ず `source` を正しく付ける。

### products/

```text
products/<key>.yaml   # key, name, vendor, sku, connector, url,
                      # components: [{chip, addr}]     (key = slug(vendor)-slug(sku))
```

product は「どの chip がどのアドレスに載るか」の正規化マッピングに徹する。`url` は公式ページを正とする。測定内容などのタグは chip 側（`tags`）。status / 別名 / 確認日 / references は持たない（url が正）。product 間の世代関係などは今後 relation で後付け。

`notes` は product / chip どちらも**任意**。意味のある固有情報のみに使う（揮発情報・別名・relation で表せる関係・構造化できる事実は入れない）。

### libraries

```text
libraries/<key>.yaml   # key, name, repo, supports.chips（1ライブラリ1ファイル）
```

- `kind` は持たない。多チップ/単チップの区別は `supports.chips` の要素数で自明。
- `versions` は持たない。実際に使った版は **library observation の provenance に pin** する（レジストリに静的な版リストを持つと重複・ドリフトするため）。
- `license` は持たない。キャプチャはライブラリを実行して観測した独自データでライブラリのライセンスに縛られない。ライセンスが要れば `repo` を辿る（保存するとドリフトする）。
- `name` は**正式なライブラリ名のみ**（著者名を混ぜない。例 `DHT12`、`DHT12 (RobTillaart)` にしない）。author / maintainer は `repo` の owner（`key` にも含まれる）から導出し、保存しない。同名ライブラリ（RobTillaart 版 / xreef 版など）の区別は key で付き、表示で著者を見せたい場合は site が name + owner を併記する。
- chips と同じく per-file にして順序・マージ衝突を避ける（ロード時に `libraries/*.yaml` を集約）。

chip ↔ library は many-to-many。**関係は library 側が `supports.chips` だけで持つ**（権威は library、更新頻度も library 側が高いため）。

`supports.chips` は「**このツールが対応した（キャプチャ対象にした）チップ**」で、ライブラリが上流で叩ける全チップの列挙ではない。**最初に全部並べず、対応したら追加**する（未検証のものは載せない）。M5Unit-ENV のように多チップ対応でも、対応済みのものだけを列挙。product 適用は `product.components` と突き合わせて導出。

> これは実質「`(chip × library)` で対応済みの一覧」なので、将来 probe / capture が揃えばそこから導出できる（その時点で明示保存をやめる選択もある）。今は明示保存する。

`chip → libraries` / `product → libraries` の逆引きはサイト生成時に導出する（保存しない）。ライブラリ追加は1エントリで完結する。

ユニット結合 API のみで chip 単位に割れないライブラリ（現状は該当なし）は、必要になった時にモデルを見直す。それまで `supports` は chips のみ。

### scenarios/

```text
scenarios/common/<scenario>.yaml
scenarios/<chip>/<scenario>.yaml
```

characterization の入力と手順を宣言する。共通 scenario を chip 固有パラメータで利用できる構造を優先する。最低限 `key`、`target`、`safety`、`inputs`、`preconditions`、`steps`、`measurements` を持つ。`steps` は低レベル I2C read / write、wait、power cycle、外部刺激の記録、UART event を表せるようにする。

`safety` は `read-only` / `reversible-write` / `destructive` 等を明示する。予約アドレス、未定義 register、EEPROM、出力制御などへの無差別アクセスを共通 sweep に含めない。

### observations/

```text
observations/<target>/<observation-id>.yaml
```

1 observation は 1 回の制御された実験を表す。期待値ではなく、与えた入力と実際の結果を保存する。

```yaml
id: bmp280-forced-measurement-001
kind: characterization
target: bmp280
scenario: bmp280/forced-measurement
inputs: {}
result: {}
captures: []
provenance:
  specimen_id: specimen-001
  product: m5stack-u001
  supply_voltage_v: 3.3
  ambient: {}
  bus: {}
  probe_firmware: {}
  instruments: []
```

- `specimen_id` はリポジトリ内だけで一貫する匿名 ID。capture identity には含めない。
- provenance は主張の再現性に影響する情報を保存する。電源、pull-up、配線、温度、bus speed、MCU / core、probe / library version、ロジアナと sample rate 等を対象とし、関係しない項目を一律必須にはしない。取得日時は既定で保存しない。
- library observation は `kind: library` と `library` / version / 呼び出し入力 / 戻り値を持つ。characterization observation は `scenario` を持つ。
- センサの物理量を検証する場合、外部刺激と基準計の値・精度を input / instruments に保存する。

### captures/

```text
captures/
  raw/       <target>__<probe>__<speed>__<condition>__<hash>.sr             # Level1（hash = decoded 内容）
  decoded/   同名.jsonl                                                      # Level2（各行に address, rw, data, ack, {operation, phase}）
```

命名例（target = chip。末尾は日付ではなく内容ハッシュ）:

```text
captures/raw/bmp280__m5stack-m5unit-env-1.0.0__400k__nominal__a1b2c3d4.sr
```

capture は既定で **chip-scoped**（target = chip）。製品非依存なので、その chip を含むどの製品でも使い回す。capture 自体は内容アドレスとし、再現環境・物理個体・product は参照元 observation に置く。ユニット結合 API の例外ライブラリのみ **unit-scoped**（key が unit）。正式なフィールド／ディレクトリ構成は schema 確定時に決める。

`captures/` に残すのは validate を通過した chip probe のバス記録である。**scan は MCU の presence マップを observation として保存するが、同時取得した LA データは capture として永続化しない**（presence の真実は MCU で、浮いたバスの LA decode はノイズ。[COLLECTION.ja.md](COLLECTION.ja.md)）。中間物（jsontrace）と収集中の作業ファイルは `collection/_staging/` に置き、次の hardware capture run 開始時にワイプする（unit test / `--collect-only` では保持する）。

decoded の 1 行イメージ（フィールドは調整前提。実装は `tools/decode.py`。絶対 timestamp は identity・内容ハッシュに含めない）:

```json
{"i": 12, "addr": "0x76", "rw": "write", "addr_ack": true, "bytes": [{"value": "0xF4", "ack": true}], "stop": true, "operation": "Initialization", "phase": "configure"}
```

時間挙動が意味を持つ observation では、絶対時刻ではなく前 transaction からの間隔、command から ready まで、clock stretch 等を `timing_features` として正規化する。値は observation ごとに保持し、複数回から min / median / max や分布を導出する。通常の内容ハッシュには含めず、timing-focused condition の比較ハッシュにのみ使用する。

## ライブラリ選定基準

各 product に対し、少数の代表的ライブラリで収集する（全候補は集めない）。

**1. ベンダー公式（必須・基準実装）** — 製品エコシステムの公式ライブラリ。

| ecosystem | vendor |
|-----------|--------|
| Unit (M5Stack) | M5Stack（M5Unit-\* / M5UnitUnified） |
| Grove | Seeed Studio |
| Qwiic | SparkFun |
| STEMMA QT | Adafruit |
| Gravity | DFRobot |
| Generic / その他 | なし |

**2. 比較用（各 chip に独立実装を最低 1 つ）** — compare の diff 対象を確保する。そのチップを叩ける大手エコシステムのライブラリ（Adafruit / SparkFun / Seeed）を優先し、無ければ評価の高いコミュニティライブラリ。

**3. 選定ゲート**

- **独立した実装**であること（既収録の fork / ミラーは不可 — 同じ通信になり比較価値がない）。
- 保守されている & 事実上の標準（Arduino Library Manager / PlatformIO 登録、star 等）。
- 再配布可能なライセンスが明確。
- repo を記録し、version は capture ごとに pin。

**4. 規模** — chip あたり 2〜3（ベンダー + 独立 1〜2）を目安に、最も代表的なものを選ぶ。

### 候補 vs 収録

- `libraries/` に置くのは**実際に収集する（probe を用意する）ライブラリ**のみ。投機的な「候補」はデータ化しない。
- 選定基準は「product に着手したとき、どの library entry を作るか」を決めるルール。
- 「選定されたが未キャプチャ」の差分（カバレッジ）は、product × 基準 と実データの突き合わせで生成時に導出する（手管理のダングリング entry を作らない）。

### U001 への適用例

probe は `(chip × library)` 単位（product は出ない）。

- **BMP280** → `bmp280__m5stack-m5unit-env`（ベンダー）+ `bmp280__adafruit-bmp280-library`（比較用）
- **DHT12** → `dht12__m5stack-m5unit-env`（ベンダー）+ `dht12__robtillaart-dht12`（比較用）
  - Adafruit / SparkFun に DHT12 の I2C ライブラリが無いため、コミュニティの独立実装を採用。

いずれも該当チップを含む他製品（ENV II / ENV IV 等）で再利用する。
