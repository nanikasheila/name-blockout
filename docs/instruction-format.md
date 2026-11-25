# 指示書（指示.json）の形式 v1

name-studio などのネームの道具と name-blockout の間の約束です。スキーマは [`schema/v1/instruction.schema.json`](../schema/v1/instruction.schema.json)（JSON Schema 2020-12）。

- **1 つの依頼に 1 ファイル**。name-studio は背景の依頼ごとに `依頼/<日時>/指示.json` を、これまでの `依頼.md`（AI 向けの言葉）と並べて書きます。
- **座標は紙面の mm**（用紙の左上が原点、右が x、下が y）。3D の長さは m、角度は度。
- **作者が描いたものをそのまま渡す**。カメラは定規（アイレベル・消失点）から name-blockout が自分で解きます。name-studio が計算したカメラは `camera.hint` に入れ、name-blockout は自分の答えと突き合わせます（食い違いは点検のエラー。指示が意図どおりに伝わっているかの確かめです）。
- 指示書は**読むだけ**。要求開発で決めたこと（答え・仮定・版）は作業フォルダーの `要求/<コマの id>.json` に別に持ちます（[phases.md](phases.md)）。

## 版

`format` は `"name-blockout/instruction"`、`formatVersion` は `1`。意味が変わる変更で版を上げ、読む側は知らない版をはっきり断ります。項目を足すだけなら同じ版のまま、スキーマに足します（知らない項目はスキーマで断るので、name-studio と name-blockout はスキーマを同じにそろえて出します）。

## 全体

| 項目 | 中身 |
| --- | --- |
| `createdBy` | 書いた道具と版（`{"app": "name-studio", "version": "0.2.170"}`） |
| `request` | 依頼の id（name-studio の依頼の日時）・作った日時・今回の注文 `note` |
| `work` | 作品名・用紙 `paperMm`・綴じ `binding`・世界の設定 `worldBrief` |
| `folders` | 作業フォルダー `background`（案/・依頼/ がある）と素材のフォルダー `assets`（素材.json がある）。相対ならこのファイルから |
| `shots` | コマごとの指示（下） |

## コマ（shot）

項目ごとに、**どのフェイズで使うか**（変えたときにどこからやり直すか）を書きます。

| 項目 | 中身 | フェイズ |
| --- | --- | --- |
| `id` | コマの id（name-studio の panel.id。名前が変わっても変わらない） | — |
| `label`・`page`・`order` | 人が読む名前（p6 コマ1）・ページ・読む順。前後のコマの点検に使う | — |
| `stage` | `blockout`（設計だけ）か `develop`（本番まで） | 開発 |
| `requirement` | 要求の版・確定かどうか・仮に置いた値（name-blockout の `要求/` と同じ形） | — |
| `frame` | 描く範囲 `boxMm`（コマの外接矩形＋塗り足し 3mm、紙面の中）・`dpi`・`sizePx`（四捨五入、書いてあれば照合）・コマの形 `shapeMm`・裁ち切り `openEdges` | 設計 |
| `intent` | 背景なし `none`・背景の指示 `brief`・カメラの言葉 `camera`（eye/low/high、定規がないとき）・演出メモ・セリフ・ページのメモ | 設計（`none`・`brief`・`camera`）、ほかは人が読むだけ |
| `ruler` | 透視の定規: `points`（0〜3）・アイレベル `horizonMm`（コマの左右の辺の上の 2 点）・消失点 `vanishingMm`（1・2 はアイレベルの上、3 は縦の線が集まる点）・XYZ の線 `guidesMm` | 設計 |
| `camera` | 定規からは決まらないこと: 高さ `heightM`・場所の中の位置 `positionM`・立ち位置の名前 `spot`・レンズ `lensMm`（消失点が 2 つ以上なら定規から決まる）と、書いた道具の計算 `hint` | 設計（`hint` は照合だけ） |
| `place` | 場所: 素材の名前 `asset`、消失点 1・2 が場所の座標のどの向きか `axes`（例 `["+X", "+Y"]`） | 設計 |
| `objects` | 物: id・名前・範囲 `shapeMm`・素材 `asset`・大きさ `sizeM` [幅, 奥行, 高さ]・どの消失点へ向かうか `axis`（1/2）・向きの言葉 `facing`・見せたい面 `show`・地面に置くか `onGround` | 設計 |
| `figures` | 人物（あたりの人形）: 頭から足までの範囲 `shapeMm`・身長 `heightM`・姿勢 `pose`・向き・足が切れているか `cut` | 設計 |
| `look` | 開発の見た目: 時間帯 `timeOfDay`・日付・緯度経度・北の向き・天気・光の狙い `light`・材質の割り当て `materials` | 開発 |
| `render` | 描き出し: 出すもの `passes`（完成・線画・トーン・影）・下見の解像度 `previewDpi` | 開発 |
| `output` | 書く案の番号 `take`（なければ次の番号） | — |

### 定規からカメラへ

name-blockout は定規から、ピンホールのカメラを次のように決めます（name-studio の `bgcamera.ts` と同じ決め方を、別の式で解きます）。

- 主点（カメラが向く所）: 2 点なら、消失点がコマの中心をはさむときは中心の真下（アイレベルの上）、そうでなければ 2 点の間。1 点なら消失点そのもの。3 点なら 3 つの消失点の三角形の垂心（見上げ・見下ろし）。定規がアイレベルだけならコマの中心の真下。
- 焦点距離: 2 点なら f² = (p − u1)(u2 − p)、3 点なら f² = d·e（主点からアイレベルまで × 主点から消失点 3 まで）。それ以外は `camera.lensMm`、なければ 35mm。
- 向き: 世界の上はアイレベルを通る光線の面の法線、世界の X は消失点 1 へ（`place.axes` があればその向き）、Y は Z × X。
- Blender へは、センサー 36mm を長い辺に（sensor fit AUTO）、レンズシフトは長い辺に対する割合。定規が傾いている（ロール）ときも主点は絵の座標で置きます。
- 高さは `camera.heightM`（なければ仮に 1.5m）。高さを変えると場の大きさが変わるだけで、絵の中のアイレベルと消失点は変わりません。

### 物と人物

物は、辺が消失点へ向かう箱として、画面の中の範囲を埋めるように置きます（大きさがなければ、範囲を埋める箱のうち、名前から分かるふつうの大きさ（`sizes.py`）の釣り合いに近いもの）。人物は足が範囲の下の端に立つように置き、頭の高さのずれでカメラの高さが合っているかを確かめます。

## 例

[`examples/two-point/指示.json`](../examples/two-point/指示.json)（2 点透視の街角、物 2 つと人物 1 人）。
