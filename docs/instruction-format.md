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
| `requirement` | 要求の版・確定かどうか・仮に置いた値（name-blockout の `要求/` と同じ形）。`answered` は、書いたアプリで作者が答えた（おまかせにした）問いの path の一覧で、`check` はそれをもう聞かない（値を決めた問いは、その値を項目に書く） | — |
| `frame` | 描く範囲 `boxMm`（コマの外接矩形＋塗り足し 3mm、紙面の中）・`dpi`・`sizePx`（四捨五入、書いてあれば照合）・コマの形 `shapeMm`・裁ち切り `openEdges` | 設計 |
| `intent` | 背景なし `none`・背景の指示 `brief`・カメラの言葉 `camera`（eye/low/high、定規がないとき）・演出メモ・セリフ・ページのメモ | 設計（`none`・`brief`・`camera`）、ほかは人が読むだけ |
| `ruler` | 透視の定規: `points`（0〜3）・アイレベル `horizonMm`（コマの左右の辺の上の 2 点）・消失点 `vanishingMm`（1・2 はアイレベルの上、3 は縦の線が集まる点）・XYZ の線 `guidesMm` | 設計 |
| `camera` | 定規からは決まらないこと: 高さ `heightM`・場所の中の位置 `positionM`・立ち位置の名前 `spot`・レンズ `lensMm`（消失点が 2 つ以上なら定規から決まる）と、書いた道具の計算 `hint` | 設計（`hint` は照合だけ） |
| `place` | 場所: 素材の名前 `asset`、消失点 1・2 が場所の座標のどの向きか `axes`（例 `["+X", "+Y"]`） | 設計 |
| `objects` | 物: id・名前・範囲 `shapeMm`・素材 `asset`・大きさ `sizeM` [幅, 奥行, 高さ]・どの消失点へ向かうか `axis`（1/2）・向きの言葉 `facing`・見せたい面 `show`・地面に置くか `onGround`・距離帯 `band`（near/middle/far） | 設計 |
| `figures` | 人物（あたりの人形）: 頭から足までの範囲 `shapeMm`・身長 `heightM`・姿勢 `pose`・向き・足が切れているか `cut` | 設計 |
| `far` | 遠景の層（奥から）: 全天球の画像 `panorama`（素材の名前 `asset`・回す角度 `turnDeg`）、道具が作る街並み `skyline`・山並み `mountains`・木立 `trees`（距離 `distanceM`・高さの幅 `heightM`・種 `seed`） | 設計 |
| `look` | 開発の見た目: 時間帯 `timeOfDay`・日付・緯度経度・北の向き・天気・光の狙い `light`・材質の割り当て `materials` | 開発 |
| `render` | 描き出し: 出すもの `passes`（完成・線画・トーン・遠景・影）・下見の解像度 `previewDpi` | 開発 |
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

### 見た目（look、開発）

| 項目 | 中身 |
| --- | --- |
| `timeOfDay` | 明け方 dawn・朝 morning・昼 noon・午後 afternoon・夕方 evening・日暮れ dusk・夜 night |
| `date`・`location`・`north` | 日付（YYYY-MM-DD か MM-DD）・緯度経度・場所の座標で北の向き（+X・+Y・−X・−Y）。太陽の位置に使う |
| `weather` | 晴れ clear・くもり cloudy・かすみ haze・どんより overcast・雨 rain・雪 snow・霧 fog |
| `setting` | 屋外 outdoor・屋内 indoor。なければ言葉（ソファ・部屋・机など）から仮に決める |
| `light.key` | 光の向きの狙い（順光 front・逆光 back・左から side-left・右から side-right・真上 top、窓から window・天井の明かり interior・街灯 street）。屋外で時間帯があれば照合に使い、なければその向きに光を置く。屋内はこの明かりで照らす（既定は天井） |
| `materials` | `[{"target": 物の id か "ground", "material": ライブラリの名前}]` |

数値への直し方と描き出しは [phases.md](phases.md#開発本番に近づける)。

### 距離帯と遠景

物と人物は、組んだ位置のカメラからの距離で **近景**（25m まで）・**中景**（250m まで）・**遠景**（その先）に分かれます（`band` で指示もできる。組んだ距離と大きく違えば計画のメモに出る）。遠いほど線を細く（近景 × 1・中景 × 0.75・遠景 × 0.55、地面の格子 × 0.5）、トーンを明るくします。

`far` の層は奥の景色です。

- `panorama`: 素材.json の全天球の画像（正距円筒、kind `panorama`。.hdr・.exr・.png・.jpg）を空にします。カメラの「上」を定規から決めているので、水平に撮れた画像なら画像の地平線（真ん中の行）がアイレベルに乗ります。合わせるのは向き `turnDeg` だけ。画像には辺がないので線は出ず、`遠景.png` にだけ入ります（完成・線画・トーンは白・透明のまま）。
  - 解像度: 画像の幅は 2π × 焦点距離（px）要ります。点検は、下見に足りなければ warn、本番（指示の dpi）に足りなければ info を出します。たいてい下見には足り、600dpi の本番には足りません（本番ではぼかした遠景・写真加工の下地の扱い）。
- `skyline`・`mountains`・`trees`: 道具が種 `seed` から作る箱の街並み・山の稜線・円錐の木立。同じ指示なら同じ形。絵が見ている向き（と少しの余り）にだけ作ります。街並みの箱は場の軸にそろうので消失点へ向かいます。
- 遠景に回せる目安: カメラの高さが 1m 違っても絵の上で 1px 動かない距離（焦点距離 px × 1m）。下見（150dpi）で 1〜2km、600dpi で 3〜7km。それより近い物は箱で組むほうが確かです（計画のメモで知らせます）。

`遠景.png` は遠景の帯（遠景の物と `far` の層、全天球の画像）だけを描いたもの。完成・線画・トーンとは別の層として渡します。

### 素材（素材.json）とライセンス

name-studio と同じ `素材.json`（`{"assets": [{"name", "kind", "file", ...}]}`）に、出どころを書きます。

| 項目 | 中身 |
| --- | --- |
| `kind` | `place`（場所）・`thing`（物）・`panorama`（全天球の画像） |
| `license` | SPDX の名前（`CC0-1.0`・`CC-BY-4.0`・`MIT` など）か、自分で作ったものは `own` |
| `source`・`author` | 出どころの URL と作者 |
| `attribution` | クレジットの書き方の指定（なければ名前・作者・出どころ・ライセンスから作る） |

無料で商用にも使えるものだけを使います（`CC0-1.0`・`CC-BY-4.0`・`CC-BY-3.0`・`MIT`・`Apache-2.0`・`BSD-2-Clause`・`BSD-3-Clause`・`Unlicense`・`0BSD`・`own`）。それ以外（非商用 NC、改変禁止 ND、継承 SA など）は読み込まず、指示が名指ししていれば点検が知らせて箱で組みます（SA を使うと決めたら `素材.json` の `"allowLicenses": ["CC-BY-SA-4.0"]` で足せます）。`license` のない素材は自分のものとして使い、点検が info で尋ねます（AI が作ったもの `by: "AI"` は尋ねない）。案ごとに使った素材を `credits.json`（`案/<コマ>/<番号>/` と `blockout/…/`）に書き、クレジットの要るものは案のメモにも 1 行足します。素材の集め方は [assets.md](assets.md)。

## 例

[`examples/two-point/指示.json`](../examples/two-point/指示.json)（2 点透視の街角、物 2 つと人物 1 人）、[`examples/three-point/指示.json`](../examples/three-point/指示.json)（見上げの 3 点透視）、[`examples/far/指示.json`](../examples/far/指示.json)（近景の小屋・中景の倉庫・遠景の山並み・街並み・木立）。
