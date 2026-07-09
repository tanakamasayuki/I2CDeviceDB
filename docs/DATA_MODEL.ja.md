# データモデル

> ステータス: 叩き台。エンティティ構成とキー方針は確定。フィールドは収集しながら追加・調整する。

## 3 + 1 のエンティティ

| エンティティ | 例 | 役割 | 再利用性 |
|--------------|-----|------|----------|
| **chip** | `bmp280`, `dht12` | I2C チップ単位のレジスタ情報・既知アドレス・プロファイル（Level5）。**汎用資産の本体・capture の既定 target** | 高（多製品で共通） |
| **product** | `m5stack-u001` | 部品表: どの chip がどのアドレスに載るか + コネクタ・ベンダー・URL。**capture の identity には入らない**（provenance と集約ビュー用） | 中 |
| **library** | `m5stack-m5unit-env` | 収集に使った実装。repo / ライセンス・対応 chip（版はキャプチャ側で pin） | — |
| **capture** | ある target の記録 | target(chip) × library × operation × bus_speed × condition で取得。decoded は transaction ごとに address を持つ | — |

## キー設計（確定）

- **product キー = `slug(vendor)-slug(sku)`（フラット）。** 例 `m5stack-u001`。中身のチップが変われば SKU が変わる（ENV = U001 / ENV II = 別 SKU …）ので SKU をキーに含める。library の `slug(owner)-slug(repo)` と同型。
- **chip キー = 型番 slug（vendor 無し）。** `bmp280`, `dht12`。部品型番はほぼグローバル識別子なので vendor で名前空間化しない（product・library は SKU/repo 名が vendor 間で衝突しうるため prefix を付ける）。BMP280 と BME280、リビジョン差など挙動が異なるものは原則別エントリ。
- **library キー = repo 由来の slug（判断の余地なく一意）。** `key = slug(owner)-slug(repo)`（`slug()` は小文字化し英数字以外の連続を `-` に置換）。ただし `slug(repo)` が `slug(owner)-` で始まる場合は `slug(repo)` のみ（owner 重複回避）。owner を含むので同名衝突（DHT12 の RobTillaart 版 / xreef 版）も区別できる。
  - 例: `m5stack/M5Unit-ENV` → `m5stack-m5unit-env` / `adafruit/Adafruit_BMP280_Library` → `adafruit-bmp280-library` / `RobTillaart/DHT12` → `robtillaart-dht12`。

## 連結

```text
product ──references──> chip     （どの chip がどのアドレスに載るか = 部品表）
capture  ──target────> chip      （その capture が叩いた対象。既定は chip）
capture  ──references─> library  （どの実装で叩いたか, version 付き）
capture  ──references─> product  （再現・集約ビュー用。identity ではない）
library  ──supports──> chip      （そのライブラリが叩けるチップ）
```

- capture の identity は `target(chip) × library × operation × bus_speed × condition`。product は入らない。
- product は再現（接続する製品）と集約ビュー（「この製品のチップのデータ」）のために参照されるだけ。
- chip 側は「取りうるアドレス一覧（アドレスピンで可変）」、product 側は「実際に使われた確定アドレス」を持つ。probe は実行時にそのアドレスをパラメータで受け取る。

## probe の分け方（呼び出し方＝コードパス単位）

probe は「あるライブラリの、ある呼び出し方が叩く対象」で分ける。**分類（製品単位/チップ単位）ではなく、呼び出し方（API・クラス・シーケンス）が違うかどうか**が基準。

- 呼び出し方が違えば別 probe。同じならまとめてターゲット（アドレス等）をパラメータ化。精度・出力の差だけで呼び出しが同じなら分けない。
- 多くのライブラリは**チップ単位に割れる**（例: M5Unit-ENV はセンサ別クラスを持つ → BMP280 用と DHT12 用に分割でき、どちらも当該チップを含む全製品で再利用）。→ probe = `(chip × library)`、product は名前に出ない。
- **例外**: チップ単位に割れず、1 呼び出しでユニット全体を叩く結合 API のライブラリだけ target=unit になる（`(unit × library)`）。この場合のみ product/unit が出る。

probe の実体・命名・フォルダは [COLLECTION.ja.md](COLLECTION.ja.md)。

## capture の同一性と派生軸

```text
capture = target × library(+version) × operation × bus_speed × condition
              │           │              │            │           └─ nominal / continuous / tight-timing / overspeed / clock-stretch
              │           │              │            └─ 100k / 400k / 800k …
              │           │              └─ UART マーカーで区切る
              │           └─ 呼び出し方（コードパス）単位の probe
              └─ 基本 chip（例外的に unit）
```

**capture は内容で識別する（コンテンツアドレス）。** identity = 論理キー `(target × library-libver × speed × condition)` ＋ **decoded 内容のハッシュ**。**日付は identity にもメタデータにも使わない**（取得日はデータの性質を表さないため）。内容が同じキャプチャは同じ名前＝自然に 1 つに畳まれ、内容が違えば別ハッシュ＝意味ある variant として残る。

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
- **1 エンティティ = 1 YAML ファイル**（手編集用マスタ）。profile（Level5）も同じ YAML に構造化して畳み込む（`chip.yaml` + `profile.md` の二重管理はしない）。
- 命名はフラット寄りにして探しやすくする（`chips/bmp280.yaml`）。
- **YAML がマスタ、JSON はビルド生成**。サイトと downstream は生成された JSON を fetch する。手で書くのは YAML、機械が読むのは JSON、で二重管理を避ける。
- 生成物（JSON / HTML）は main に置かず、サイトは gh-pages ブランチへ公開する（[SITE.ja.md](SITE.ja.md)）。

## ディレクトリと最小スキーマ

### chips/

```text
chips/<chip>.yaml   # key, name（= 型番 part number）, manufacturer, tags, addresses: [{addr, note?}],
                    # datasheets: [{source, vendor?, url, revision?, date?}],
                    # registers: [{name, addr, len?, desc?}], notes
```

### chip profile の深さ

**書くのはデコード凡例まで。データシートの転記はしない。**

- `registers` は「`addr`（開始）→ `name` → 一言 `desc`」の最小凡例（キャプチャの `write 0xF4` を `ctrl_meas` と表示するため）。複数バイトは `len`（省略時 1）。**ビットフィールド・有効値・パラメータ定義は書かない**（データシート = `datasheets` リンクが正）。
- **アドレス範囲を `"0xF7..0xFC"` のような非パース文字列で書かない**。`addr: "0xF7", len: 6` のように機械可読にする。
- `sequences`（通信シーケンス）/ known responses / この chip を使う captures への逆引きは**保存しない**。すべて**キャプチャから導出**する（build / site 時）。手編集で埋める placeholder は持たない。
- 網羅（全レジスタ・全機能）は追わない。凡例は**観測されたものを育てる**（データシートから名前を付ける）。ライブラリが全機能を叩いているかの確認も DB の責務にしない（必要なら別枠の合成 feature-sweep として明示）。

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
- `versions` は持たない。実際に使った版は**キャプチャ側（Level3 メタデータ）に pin** する（レジストリに静的な版リストを持つと重複・ドリフトするため）。
- `license` は持たない。キャプチャはライブラリを実行して観測した独自データでライブラリのライセンスに縛られない。ライセンスが要れば `repo` を辿る（保存するとドリフトする）。
- `name` は**正式なライブラリ名のみ**（著者名を混ぜない。例 `DHT12`、`DHT12 (RobTillaart)` にしない）。author / maintainer は `repo` の owner（`key` にも含まれる）から導出し、保存しない。同名ライブラリ（RobTillaart 版 / xreef 版など）の区別は key で付き、表示で著者を見せたい場合は site が name + owner を併記する。
- chips と同じく per-file にして順序・マージ衝突を避ける（ロード時に `libraries/*.yaml` を集約）。

chip ↔ library は many-to-many。**関係は library 側が `supports.chips` だけで持つ**（権威は library、更新頻度も library 側が高いため）。

`supports.chips` は「**このツールが対応した（キャプチャ対象にした）チップ**」で、ライブラリが上流で叩ける全チップの列挙ではない。**最初に全部並べず、対応したら追加**する（未検証のものは載せない）。M5Unit-ENV のように多チップ対応でも、対応済みのものだけを列挙。product 適用は `product.components` と突き合わせて導出。

> これは実質「`(chip × library)` で対応済みの一覧」なので、将来 probe / capture が揃えばそこから導出できる（その時点で明示保存をやめる選択もある）。今は明示保存する。

`chip → libraries` / `product → libraries` の逆引きはサイト生成時に導出する（保存しない）。ライブラリ追加は1エントリで完結する。

ユニット結合 API のみで chip 単位に割れないライブラリ（現状は該当なし）は、必要になった時にモデルを見直す。それまで `supports` は chips のみ。

### captures/

```text
captures/
  raw/       <target>__<library>-<libver>__<speed>__<condition>__<hash>.sr   # Level1（hash = decoded 内容）
  decoded/   同名.jsonl                                                      # Level2（各行に address, rw, data, ack, {operation, phase}）
```

命名例（target = chip。末尾は日付ではなく内容ハッシュ）:

```text
captures/raw/bmp280__m5stack-m5unit-env-1.0.0__400k__nominal__a1b2c3d4.sr
```

capture は既定で **chip-scoped**（target = chip）。製品非依存なので、その chip を含むどの製品でも使い回す。メタデータは**再現に必要な環境のみ**（[SPEC.ja.md](SPEC.ja.md) のメタデータ節）で、日付・物理個体は持たない。ユニット結合 API の例外ライブラリのみ **unit-scoped**（key が unit）。正式なフィールド／ディレクトリ構成は schema 確定時に決める。

decoded の 1 行イメージ（フィールドは調整前提）:

```json
{"ts": 0.001234, "addr": "0x76", "rw": "w", "data": ["0xF4", "0x27"], "ack": [true, true], "operation": "Initialization", "phase": "configure"}
```

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
