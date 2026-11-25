# 素材の集め方

Blockout を速くし、開発（本番）で詳しくするための素材は、**無料で商用にも使えるもの**だけを、出どころとライセンスを `素材.json` に書いて使います（[instruction-format.md](instruction-format.md#素材素材jsonとライセンス)）。name-blockout は書かれたライセンスで関所を通し、使った素材を案ごとの `credits.json` に残します。

## 距離帯ごとの用意

| 距離帯 | Blockout（設計） | 開発（本番） |
| --- | --- | --- |
| 近景（〜25m） | 箱・人形（道具が作る） | 物の素材（.blend）。同じ名前の素材の詳しい版 |
| 中景（〜250m） | 箱（ふつうの大きさから） | 建物・木の素材、建物の並び |
| 遠景（その先） | 種から作る街並み・山並み・木立、全天球の画像 | 同じ層をそのまま（線を細く・トーンを明るく）、全天球の画像はぼかした下地 |

遠景の層は、Blender のジオメトリノードではなく name-blockout の Python で作っています。同じ種から同じ形が出ること、Blender なしでテストできること、計画（plan.json）に形がそのまま残って照合や見直しに使えることを優先しました。手で作ったジオメトリノードの部品も、.blend の素材（`kind: "thing"`、コレクションで指定）として置けば使えます。

## 出どころの候補

| 出どころ | ライセンス | 使いどころ | 注意 |
| --- | --- | --- | --- |
| [Poly Haven](https://polyhaven.com/)（HDRI・モデル・テクスチャ） | CC0 | 全天球の画像（遠景・空）、小物 | 一番使いやすい。HDRI は 16K まで（本番の解像度には足りないことが多い） |
| [ambientCG](https://ambientcg.com/)（テクスチャ・HDRI） | CC0 | 開発の質感 | |
| [nvidia/simready-assets](https://huggingface.co/datasets/nvidia/simready-assets) | データセットのカードは CC BY 4.0 | 倉庫・台所・車の部品などの物 | USD 形式（Blender で読み込める）。全体で約 518GB あるので、要るものだけ落とす。クレジットが要る |
| [nvidia/simready-central](https://huggingface.co/spaces/nvidia/simready-central) | 素材ごとに違う | 物 | **1 件ずつライセンスを確かめる**。CC BY 4.0 などの商用可だけを 素材.json に（不明なものは使わない） |

使わないもの: 非商用（NC）・改変禁止（ND）・ライセンスの書かれていない配布物・利用規約で競合ツールの参考を禁じているサービス。継承（SA）は既定では使いません（使うと決めたら `allowLicenses` に足す）。

## 素材.json の例

```json
{
  "assets": [
    {"name": "曇り空", "kind": "panorama", "file": "空/overcast_8k.hdr",
     "license": "CC0-1.0", "source": "https://polyhaven.com/a/<その画像の id>", "author": "<ページに書かれた作者>"},
    {"name": "台車", "kind": "thing", "file": "物/cart/cart.blend", "collection": "cart",
     "license": "CC-BY-4.0", "source": "https://huggingface.co/datasets/nvidia/simready-assets", "author": "<ページに書かれた作者>",
     "note": "幅 0.6m・奥行 1.0m。持ち手が -Y"}
  ]
}
```

（例の名前とファイルは書き方の見本です。実際に落としたときに、その素材のページのライセンスと作者を写してください。）

物の素材（`kind: "thing"`）は、作画（開発）のときに箱の代わりに置かれます。置き方は次のとおりです。
- 素材の正面を −Y（Blender の「前」）に向けて作っておくと、正面がカメラを向きます。
- 縦・横・高さを同じ割合で縮めて、ネームの範囲から決めた箱に収めます。素材の形は変えません。
- 床（素材の一番下）は箱の底にそろえます。

素材の中の部品（オブジェクト）の名前を `look.materials` の `target` に書くと、その部品だけ別の材質になります（例: `{"target": "座面", "material": "黒い塗装"}`）。
