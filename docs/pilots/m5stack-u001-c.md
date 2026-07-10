# ENV III pilot checklist

> 対象: `m5stack-u001-c`（SHT30 `0x44` + QMP6988 `0x70`）  
> ステータス: planning  
> 役割: profile schema と収集範囲を実機で固めるための一時的な作業計画。この文書を全 chip の恒久 TODO 形式にはしない。

## 暫定機材での初回 run（2026-07-10）

正式な複数個体評価ではなく、収集系と scenario の成立確認として扱う。

- scan は `0x44` と `0x70` の ACK を確認した。追加の `0x00` 応答は general-call
  address の候補として記録し、製品 component の追加とは解釈しない。scan の合否は BOM の
  expected address がすべて存在するかで判定し、追加応答は observation に残す。
- SHT30 は presence、soft reset、status + CRC、high / medium / low の polling 測定、
  medium / low の clock-stretch 測定まで成立した。high clock-stretch read だけ 6.759 ms で
  0 byte となった一方、同じ high 条件の polling は 13.101 ms で成功した。device failure と
  即断せず、ESP32-S3 controller の SCL-low timeout / capability 差として保存・再検証する。
- QMP6988 は presence、chip ID `0x5c`、reset default、25-byte calibration、forced 測定、
  normal mode 10 sample が成立した。forced 完了後は `DEVICE_STAT.measure=0` でも
  `CTRL_MEAS=0x25` を readback したため、「内部状態が sleep に戻ること」と「mode field の
  readback が sleep 値になること」を別の性質として扱う。
- この run の pytest 失敗は上記の差異を probe failure としていた判定による。以降は presence、
  必須 event、frame 長など収集の構造破損だけを失敗とし、controller timeout や register
  readback の差は event と probe summary に保存して run を完走させる。
- raw capture は保存済み。UART marker 内の JSON の double quote により sigrok JSON Trace が
  不正 JSON になる問題が見つかったため、offline decoder で当該 UART byte を復元する。

## 到着前の準備状況

- [x] `sht30__characterize` の safe P0 firmware / pytest driver。
- [x] `qmp6988__characterize` の safe P0 firmware / pytest driver。
- [x] `--product m5stack-u001-c` から scan + 2 probe を導出。
- [x] USB serial `EVENT` + raw / decoded + provenance の observation 候補生成。
- [x] ESP32-S3 core 3.3.10 で両 firmware をコンパイル確認。
- [x] scenario plan とハード不要テスト。
- [ ] 実機到着後に GPIO、電源、pull-up、serial、sigrok channel をベンチに合わせる。
- [ ] 100kHz の初回 run をレビュー後、400kHz と反復収集へ進む。

## 目的

基本カタログの拡充とは独立して、性質の異なる 2 chip を生成まで一巡させる。

- **SHT30**: command、response frame、CRC、NACK polling、clock stretch、periodic state、volatile value。
- **QMP6988**: register / field、reset default、個体固有 calibration、forced / normal / sleep、status、IIR、conversion。
- observation / capture から profile を整理し、アクセスライブラリとエミュレータの小さな生成試作でデータの過不足を確認する。
- 安定した調査項目を `scenarios/` と profile `coverage` へ昇格し、人間向け知見を `guides/chips/` へ整理する。

## 非目標

- 初回から全機能・全設定組み合わせを網羅しない。
- センサ精度の校正機関レベルの評価は行わない。
- general call reset、未定義領域、予約 bit、I2C high-speed mode、overspeed を初回対象にしない。
- 実測 1 回の結果を一般仕様として自動確定しない。

## 進捗語彙

チェック項目には必要に応じて次の状態を併記する。

| 状態 | 意味 |
|------|------|
| `planned` | 手順だけ決まっている |
| `collecting` | 実機収集中 |
| `observed` | observation / capture がある |
| `curated` | profile に反映済み |
| `validated` | 生成物または独立実装で確認済み |
| `deferred` | 理由を記録して今回は見送る |

単なる完了チェックで `observed` と `validated` を混同しない。

## ベンチと個体

### 個体計画

- [ ] ENV III を可能なら同一 SKU で 3 台用意する。
- [ ] 各製品に匿名 `specimen_id` を割り当てる。
- [ ] 1 台目で全 P0 と選択した P1 scenario を実行する。
- [ ] 2、3 台目で presence、identity、reset、主要測定、calibration、timing を反復する。
- [ ] 外観マーキングや明確な hardware revision 差があれば provenance に記録する。

### 共通 provenance

- [ ] product key、specimen ID、取得日時。
- [ ] 電源電圧、pull-up、ケーブル、SDA / SCL / UART 配線。
- [ ] MCU、fqbn、platform / core、probe firmware revision。
- [ ] bus speed、condition、ロジアナ、sample rate。
- [ ] library probe の場合は library key と解決済み version。
- [ ] 外部刺激と基準計を使う場合は instrument、値、単位、精度。

### 初期反復数

- deterministic 操作: 各対象個体 3 run。
- timing 操作: 各条件 20 sample を 1 capture 内にまとめる。
- 安定環境の連続値: 各対象個体 50 sample。
- nominal bus speed: 100kHz / 400kHz。
- 全組み合わせを全個体で回さず、1 台目の全 P0 + 他個体の代表条件とする。

## 共通パイプライン

- [ ] scan の MCU presence map を observation として保存する。
- [ ] SHT30 `0x44` と QMP6988 `0x70` を別 target として扱う。
- [ ] scenario / API input と MCU / library result を構造化 event で保存する。
- [ ] raw `.sr`、decoded transaction、相対 timing feature を observation から参照する。
- [ ] exact content hash と、volatile / per-specimen 値を除外した semantic signature を区別できるか検証する。
- [ ] START / repeated START / STOP、address ACK、各 byte ACK / NACK を欠落なく保持する。
- [ ] 同じ operation を characterization probe と library probe で比較する。

## SHT30

### P0: transport / identity

- [ ] `0x44` の address ACK と、製品上で `0x45` が NACK であることを確認する。
- [ ] 16-bit command の byte order と transaction boundary を確認する。
- [ ] result read の終端 NACK / STOP を確認する。
- [ ] 100kHz / 400kHz で同じ protocol sequence が成立することを確認する。

### P0: reset / status

- [ ] soft reset `0x30A2` を実行する。
- [ ] reset ACK から再応答可能になるまでの時間を測る。
- [ ] status read `0xF32D` の 16-bit value と CRC を保存する。
- [ ] reset detected、command status、write checksum status を構造化する。
- [ ] clear status 前後を比較する。

### P0: single-shot without clock stretch

- [ ] high / medium / low repeatability の command を実行する。
- [ ] command 直後の read が data 未準備時に NACK となることを観測する。
- [ ] read address が ACK へ変わるまで poll し、command → ready の時間を保存する。
- [ ] temperature 2 byte + CRC + humidity 2 byte + CRC の frame を保存する。
- [ ] CRC-8 の成否、raw 16-bit 値、℃ / %RH 変換値を別フィールドで保存する。
- [ ] repeatability ごとの timing 分布を比較する。

### P0: single-shot with clock stretch

- [ ] high / medium / low repeatability の stretch command を実行する。
- [ ] read address ACK 後に SCL が LOW 保持される位置を確認する。
- [ ] stretch count、最大 LOW 時間、合計 LOW 時間、解除位置を保存する。
- [ ] 100kHz / 400kHz と repeatability ごとの stretch 時間を比較する。
- [ ] master timeout の設定値と timeout 発生有無を observation に残す。
- [ ] stretch 有効 / 無効で result frame と変換結果の構造が同じことを確認する。

### P0: variability / stimulus

- [ ] 室内静置で 50 sample を取得する。
- [ ] temperature / humidity raw を `volatile` として扱う。
- [ ] 同一個体内変動と個体間差を分けて集計する。
- [ ] 穏やかな温度変化、湿度変化、通常環境への回復を記録する。
- [ ] exact payload を保存したまま semantic compare で測定値をマスクできるか確認する。

### P1: periodic mode

- [ ] まず 1Hz / high repeatability で periodic mode を開始する。
- [ ] 最初の data-ready、fetch `0xE000`、更新周期を観測する。
- [ ] data 未準備時の fetch / read NACK を観測する。
- [ ] fetch 後の data 消費挙動を確認する。
- [ ] break `0x3093` 後に single-shot mode へ戻ることを確認する。
- [ ] 必要性を確認後、0.5 / 2 / 4 / 10Hz と他 repeatability へ広げる。

### P1: heater

- [ ] 短時間の heater enable / disable scenario を安全区分 `reversible-write` で作る。
- [ ] status の heater flag と温湿度の時間変化を記録する。
- [ ] 最大実行時間と cooldown を scenario に明記する。

### Deferred

- [ ] ALERT limit write / pin observation — Unit で pin を利用できるか確認後に判断する。
- [ ] general call reset — 同じ bus の他 device に影響するため初回対象外。
- [ ] nRESET pin — Unit でアクセスできる場合のみ検討する。
- [ ] 長時間高湿度・精度校正 — 通信 / profile schema の検証後に判断する。

## QMP6988

### P0: identity / reset defaults

- [ ] `0xD1` の chip ID `0x5C` を確認する。
- [ ] reset `0xE0 <- 0xE6` を実行する。
- [ ] reset 前後の `0xF1`〜`0xF5` と `DEVICE_STAT` を保存する。
- [ ] `measure` / `otp_update` bit の変化と予約 bit を構造化する。
- [ ] reset から register read が安定するまでの時間を測る。

### P0: per-specimen calibration

- [ ] `0xA0`〜`0xB8` の 25 byte を burst / individual read で取得する。
- [ ] 同一個体で複数回読み、byte 列が安定していることを確認する。
- [ ] 複数個体で比較し `per_specimen` として分類する。
- [ ] signedness、endianness、bit packing を構造化した coefficient へ展開する。
- [ ] raw calibration byte と展開済み coefficient の両方を保持する。

### P0: forced measurement

- [ ] sleep mode から最小 averaging 設定で forced measurement を開始する。
- [ ] `DEVICE_STAT.measure` の 0 → 1 → 0 を poll して timing を保存する。
- [ ] 測定完了後に power mode が sleep へ戻ることを確認する。
- [ ] `0xF7`〜`0xFC` を 6 byte burst read する。
- [ ] raw pressure / temperature の byte order、offset、符号を確認する。
- [ ] calibration を使った compensated temperature / pressure を計算する。
- [ ] raw、coefficient、計算途中、最終物理量を区別して保存する。

### P0: normal measurement

- [ ] 代表 standby 値 1 つで normal mode を開始する。
- [ ] measure / standby の繰り返しと data 更新周期を観測する。
- [ ] 連続 6 byte read の一貫性を確認する。
- [ ] sleep へ明示遷移し、その後 data が更新されないことを確認する。

### P0: configuration semantics

- [ ] `CTRL_MEAS` の temperature averaging、pressure averaging、power mode を readback する。
- [ ] `IO_SETUP` の standby と reserved bit 保持規則を確認する。
- [ ] `IIR` の writable field、reset value、書き込み副作用を確認する。
- [ ] read-modify-write 時に reserved bit を破壊しない生成規則を検討する。

### P1: oversampling / IIR

- [ ] oversampling の代表値 1x / 8x / 32x で測定時間と raw 分散を比較する。
- [ ] IIR off / 2 / 8 / 32 で静置ノイズと変化への追従を比較する。
- [ ] IIR register write 時の filter 初期化を観測する。
- [ ] 全組み合わせではなく、差が profile / emulator に必要な軸だけ残す。

### Deferred

- [ ] I2C high-speed mode。
- [ ] SPI mode / SPI-only field の実機検証。
- [ ] 全 oversampling × standby × IIR の直積。
- [ ] 予約 bit / 未定義 register への書き込み。
- [ ] 精密圧力校正。

## Library probe

- [ ] SHT30 の vendor 実装と独立実装を最低 1 つずつ選定する。
- [ ] QMP6988 の vendor 実装と独立実装を最低 1 つずつ選定する。
- [ ] 実際に解決した version、API input、戻り値を observation に保存する。
- [ ] initialization、single measurement、continuous / periodic、reset の transaction 差を比較する。
- [ ] library が fixed delay、NACK polling、clock stretch のどれを使うか分類する。
- [ ] library の compensated output と canonical raw / conversion を比較する。

## 生成実証

### Access library

- [ ] SHT30 の reset、status、single-shot、CRC、raw conversion を生成する。
- [ ] SHT30 の stretch / polling を呼び出し側 capability で選択できるか検討する。
- [ ] QMP6988 の identity、calibration read、field API、forced measurement、conversion を生成する。
- [ ] reserved bit を守る read-modify-write を生成する。

### Emulator

- [ ] SHT30 の command state、NACK-until-ready、clock stretch、CRC、periodic state を再現する。
- [ ] SHT30 の temperature / humidity を外部 stimulus として注入できるようにする。
- [ ] QMP6988 の register defaults、per-specimen calibration、forced → sleep、normal update を再現する。
- [ ] QMP6988 の pressure / temperature と時間進行を外部 stimulus として注入できるようにする。
- [ ] 収集に使ったものとは別の library で生成 emulator を操作する。

## Pilot で決める schema 課題

- [ ] `register-map` / `command` transport の共通表現。
- [ ] command request / response frame と CRC。
- [ ] `constant` / `reset_default` / `per_specimen` / `volatile` / `state_dependent` / `derived` の variability 語彙。
- [ ] exact content hash と semantic signature の責務。
- [ ] transaction 間隔、ready、clock stretch、更新周期の timing 表現。
- [ ] state transition と時間経過による effect の表現。
- [ ] raw、校正係数、変換途中、物理量の conversion 表現。
- [ ] profile item から datasheet / observation への evidence 表現。
- [ ] coverage の feature 粒度と `generator-ready` 判定条件。

## Tips 候補

調査中はここへ候補だけを記録し、一般化できたものを `guides/chips/<chip>.md` へ移す。

### SHT30

- clock stretch command と non-stretch command の使い分け。
- periodic mode では clock stretch を選べない点。
- CRC は temperature / humidity の各 2 byte ごとに付く点。
- data 未準備時の NACK と通信エラーを区別する方法。
- periodic mode 中に別 command を送る前の break。

### QMP6988

- calibration の特殊な bit packing と個体差。
- forced mode 完了後に sleep へ戻る点。
- raw値と compensated値を混同しないこと。
- reserved bit を保持する read-modify-write。
- IIR register write で filter が初期化される点。

## 昇格ルール

- 繰り返し可能な収集手順 → `scenarios/common/` または `scenarios/<chip>/`。
- 確認済みの通信・行動規則 → `profiles/<chip>.yaml`。
- 実験入力・結果・環境 → `observations/`。
- raw / decoded バス記録 → `captures/`。
- 人間向けの注意・互換性情報 → `guides/chips/<chip>.md`。
- profile 対応状況 → `coverage`。pilot の checkbox を恒久 TODO として複製しない。

## Pilot 完了条件

- [ ] SHT30 P0 が observation / capture / profile に反映されている。
- [ ] QMP6988 P0 が observation / capture / profile に反映されている。
- [ ] 主要規則が datasheet または observation へ追跡できる。
- [ ] 主要 variability と timing が exact capture を失わず比較できる。
- [ ] SHT30 / QMP6988 の最小 access library を生成できる。
- [ ] SHT30 / QMP6988 の主要状態を emulator で再現できる。
- [ ] 独立 library による conformance を通せる。
- [ ] 未調査・deferred 機能が coverage に明示されている。
- [ ] 共通 scenario、profile schema、guide の初版へ知見を昇格できている。

## References

- [M5Stack Unit ENV-III](https://docs.m5stack.com/en/unit/envIII)
- [Sensirion SHT3x-DIS Datasheet, Version 7](https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf)
- [QMP6988 Datasheet, Revision C](https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/docs/datasheet/unit/enviii/QMP6988%20Datasheet.pdf)
