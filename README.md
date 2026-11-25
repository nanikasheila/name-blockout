# name-blockout

ネーム（漫画の絵コンテ）の指示から、Blender で背景の **Blockout（あたり）** を数秒で組み、狙いどおりかを**数値で確かめる**道具です。[name-studio](https://github.com/nanikasheila/name-studio) の「作画」の欄と組んで使います。

- **要求開発** → **設計（Blockout）** → **開発（本番の作画）** の 3 フェイズ。ネームの案出しは設計まで、作画に移ると決めたコマだけ開発へ（[docs/phases.md](docs/phases.md)）。
- コマに引いた透視の定規（アイレベル・消失点）から、カメラ（レンズ・シフト・見上げ/見下ろし・傾き）を計算で決めます。AI にカメラを合わせさせません。
- 組んだシーンを Blender 自身の投影で測り、指示とのずれ（px・度・重なり）を出します。合った絵だけが案として name-studio に届きます。
- 物は距離で近景・中景・遠景に分け、遠いほど線を細く・トーンを明るく。奥は全天球の画像（HDRI）や、種から作る街並み・山並み・木立で埋め、`遠景.png` として別に渡します。
- 素材は無料で商用にも使えるものだけ。`素材.json` にライセンスと出どころを書き、使った素材は案ごとにクレジットを残します（[docs/assets.md](docs/assets.md)）。
- 指示の形式（指示.json）は [docs/instruction-format.md](docs/instruction-format.md) とスキーマ [schema/v1](schema/v1/instruction.schema.json)。

## 使い方

Blender 5.x が入っていれば、追加のインストールなしに Blender から動きます。

```sh
# Blender から（Windows なら "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"）
blender -b --factory-startup --python src/name_blockout/blender/run.py -- blockout 依頼/20261126-0100/指示.json

# Python から（Blender は自動で探す。NAME_BLOCKOUT_BLENDER で指定も可）
pip install -e ".[schema]"
name-blockout check    依頼/20261126-0100/指示.json   # 要求の点検と次の質問
name-blockout answer   依頼/20261126-0100/指示.json --shot panel12 --set camera.heightM=1.2
name-blockout confirm  依頼/20261126-0100/指示.json --shot panel12
name-blockout blockout 依頼/20261126-0100/指示.json   # 組んで照合して描き出す
name-blockout scope    依頼/20261126-0100/指示.json --shot panel12   # 直したらどこからやり直すか
```

`blockout` は作業フォルダー（指示書のある `依頼/<id>/` の 2 つ上）に、name-studio がそのまま読める形で書きます。

```
<作業フォルダー>/
  案/<コマ>/<番号>/完成.png・線画.png・トーン.png（・遠景.png・credits.json）
  依頼/<id>/背景.json          ← 1 案 1 件（照合の結果はメモに）
  blockout/<コマ>/<番号>/      ← plan.json・measured.json・check.json・scene.blend
  要求/<コマ>.json             ← 要求開発の答えと版
```

## 開発

```sh
pip install -e ".[test,blender]"   # bpy（Blender を Python のモジュールとして）も入る
pytest -q                          # Blender のテストは bpy があるときだけ
ruff check src tests && ruff format --check src tests
```

- `src/name_blockout/` の Blender 以外の部分は標準ライブラリだけで動きます（Blender の Python でも）。`blender/` だけが bpy を使います。
- 描き出しは Cycles の CPU と Freestyle（EEVEE は GPU のない所で動かないため）。

## ライセンス

GPL-3.0-or-later（[LICENSE](LICENSE)）。ライセンスのない・非商用限定のプロジェクトのコードは写しません。素材は無料・商用可のものだけを、出どころとライセンスを記録して使います。
