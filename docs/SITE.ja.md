# サイト / 公開設計

> ステータス: 大方針のみ確定。実装はこれから。

## 原則

> **正規の成果物は JSON データ。サイトはその JSON を人間向けに描画する最初の消費者にすぎない。**

サイトが無くてもデータは価値がある（再利用できるデータ資産）。サイトはライブラリ開発者が使うのと同じ JSON を読んで表示するだけ。

## 公開方式（確定）

GitHub Pages は `/` か `/docs` か別ブランチのみ公開可能。**生成物（HTML / JSON）を main に混ぜない**ため：

- **GitHub Actions でビルド → `gh-pages` ブランチへ公開。**
- main は「YAML マスタ + docs + tools + firmware + captures」だけの綺麗な状態を保つ。
- ビルドで YAML/JSONL → HTML + JSON を生成し、captures もコピーして公開（ダウンロード可能にする）。

## ビルドの流れ（想定）

```text
main の chips/ + profiles/ + その他 YAML マスタ + observations/ + captures/
    ↓ tools/ のサイトジェネレータ（GitHub Actions）
catalog + profile を key で統合
    ↓
HTML（静的） + chip 単位 JSON（データ） + captures コピー
    ↓
gh-pages ブランチ → GitHub Pages
```

- **静的 JSON を生成し、ブラウザ内の JS で動的に描画する**（サーバ動的ではない）。エンティティ毎に HTML を大量生成（explosion）はしない。
- **重い部分はクライアント JS で遅延ロード**：通信ビューア（大きい decoded .jsonl）はページを開いたときだけ fetch して描画。全トランザクションを初期ロードに載せない。
- フレームワークの重さは避け、素の JS + fetch から始める。

詳細は「データ配信アーキテクチャ」を参照。

## データ配信アーキテクチャ

データを 2 階層に分け、それぞれ最適な方式で配信する（要件が真逆のため）。

| 階層 | 中身 | サイズ | アクセス | 検索/フィルタ |
|------|------|--------|----------|---------------|
| カタログ | chips / products / libraries + profile coverage + observation 索引 | 小〜中 | 一覧・横断検索 | 必要 |
| キャプチャ詳細 | decoded トランザクション列（.jsonl） | 大（1 キャプチャごと） | 1 件ずつ開く | 基本不要 |

### カタログ → 1 本の `index.json` + JS メモリ内フィルタ

- ビルドで YAML → `index.json` を生成。ロード 1 回で全検索 / フィルタ / ソートが即応（`Array.filter` で十分、検索ライブラリ不要）。
- `chips/<key>.yaml` だけの chip も index に掲載し、profile の有無と `coverage.status` を表示する。profile がない chip を非対応・機能なしとして除外しない。
- 詳細ページ / downstream 用には `chips/<key>.yaml` と任意の `profiles/<key>.yaml` を結合した chip JSON を生成する。重複フィールドや孤立 profile はビルドエラーにする。
- SQLite は不要。

### キャプチャ詳細 → 1 キャプチャ 1 JSON、lazy fetch

- キャプチャを開いたときだけ該当 JSON を fetch。全部は読み込まない。初期ロードを軽く保つ。

### SQLite（sql.js / WASM）はいつ？ → 今は不要、後付け可能

次の場合のみ導入を検討する。SQLite も「YAML/JSONL を正とした生成物の一つ」なので、後からビルドに追加するだけで済む（deferrable）。

1. `index.json` がメモリ内で辛くなる（数 MB 超）。
2. トランザクションレベルの横断検索（例: 「レジスタ 0xF4 に 0x27 を書くキャプチャ」「reset 0xB6 を送る通信」）が欲しくなる。

### 判断ルール（目安）

- `index.json` が 〜数 MB → メモリ内 JSON フィルタ（初期の推奨）。
- 数 MB 超 or トランザクション横断検索が必要 → prebuilt SQLite を追加生成し sql.js で query。
- どちらの場合も、per-capture の重いデータは常に lazy fetch。HTML の per-entity 大量生成はしない。

## 言語

- **サイトは英語中心。**
- 内部データ（`notes` / `desc` など）は英語で統一。必要になれば後から一括翻訳・`{en, ja}` 構造化に拡張する。
- 仕様書・docs は当面日本語で固め、安定後に英語を追加。

## 見せたいもの（利用者視点）

| 見せたいもの | データ源 | 生成方式 |
|--------------|----------|----------|
| どんなデバイスか（カタログ） | chips / products | 静的 |
| どうアクセスするか（register / command / operation） | chip behavior profile | 静的 |
| どの根拠で確認したか | evidence → observation / datasheet | 静的 + 詳細遅延ロード |
| 既存実装がどう呼び出すか | library observation × operation | 静的 |
| 実際に流れる通信 | decoded transaction（.jsonl） | クライアント fetch |

profile ビューは **デバイス → transport / register / command / operation / state / timing → evidence** を辿れるようにする。observation / capture ビューは **デバイス → characterization scenario または library → 操作 → 入力・結果・provenance → decoded transaction** とする。同一操作を別ライブラリ・別 specimen・別条件で並べる compare もこの延長で表示する。

## 複数データの表示（代表と差分）

収集は無制限なので、同じ論理キー `(target × probe × operation × speed × condition)` に複数の observation / capture が溜まる。**「見るべきものが分からなくなる」のを防ぐため、表示側で絞る**。

- グループ内が**一致**していれば **代表を 1 つだけ**表示（他は「N 件・同一」と畳む）。
- **食い違う**ときだけ「ここが違う」を強調（compare 由来の差分。版差 / 速度・条件差 / 内容差）。差が出る所は自動フラグ＋必要なら手書き note。
- 代表の選び方（例: 最新版・nominal・canonical）とグループ化キーは実装時に確定。
- グループ内の差異軸（scenario / ライブラリ版・速度・条件・匿名 specimen・環境など）で切り替えて見られるようにする。取得日時・specimen は provenance として表示できるが、identity や代表選択の主軸にはしない。
