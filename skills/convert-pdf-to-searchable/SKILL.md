---
name: scan-pdf-to-searchable
description: スキャンPDFをndlocr-liteでOCRし、透明テキストを埋め込んで検索可能PDFに変換する。ユーザーがスキャンPDFを検索可能にしたい、テキスト埋め込みしたい、OCRしたPDFを作りたいと言った場合に使用する。
---

# scan-pdf-to-searchable

スキャンPDF（テキストデータのないPDF）をndlocr-liteでOCR処理し、透明テキストレイヤーを埋め込んで検索可能PDF（Searchable PDF）に変換するスキルです。

## 必要ツール・依存パッケージ

このスキルの実行には以下のツールとパッケージが必要です。
**実行前に、未インストールのもののみをインストールしてください。**

### システムツール

| ツール | 用途 | 確認コマンド |
|--------|------|-------------|
| Python 3.10以上 | スクリプト実行 | `python3 --version` |
| uv | Pythonパッケージ管理 | `uv --version` |

### ndlocr-lite

ワークスペース内の `ndlocr-lite/` ディレクトリにクローン済みであること。
未クローンの場合は以下を実行:

```bash
git clone https://github.com/ndl-lab/ndlocr-lite
cd ndlocr-lite
```

ndlocr-lite自体の依存パッケージ（onnxruntime, numpy, opencv-python-headless 等）は `ndlocr-lite/requirements.txt` で管理されています。

### Pythonパッケージ（変換スクリプト用）

変換スクリプト `convert.py` が直接使用するパッケージは以下の3つです:

| パッケージ | 用途 | importチェック |
|-----------|------|---------------|
| pypdfium2 | PDFページを画像としてレンダリング | `python -c "import pypdfium2"` |
| reportlab | 透明テキストレイヤーPDFの作成 | `python -c "import reportlab"` |
| pypdf | 元PDFとオーバーレイPDFの合成 | `python -c "import pypdf"` |

> **NOTE**: `pypdfium2` と `reportlab` は ndlocr-lite の `requirements.txt` に含まれています。`pypdf` のみ追加インストールが必要です。

### インストール手順

ndlocr-liteのvenvを基盤として使用します。以下の手順で未インストールパッケージのみをインストールしてください:

```bash
# ndlocr-liteのディレクトリに移動
cd <workspace>/ndlocr-lite

# ndlocr-liteの依存を一括インストール（pypdfium2, reportlab 等もここで揃う）
uv pip install -r requirements.txt --python .venv/bin/python

# pypdfは ndlocr-lite の requirements.txt に含まれていないため追加インストール
uv pip install "pypdf[crypto]" --python .venv/bin/python
```

> **NOTE**: インストール状況を確認したい場合は、以下のワンライナーでチェックできます:
> ```bash
> <workspace>/ndlocr-lite/.venv/bin/python -c "
> import importlib
> for p in ['pypdf','pypdfium2','reportlab']:
>     try:
>         importlib.import_module(p); print(f'  ✅ {p}')
>     except ImportError:
>         print(f'  ❌ {p} — 未インストール')
> "
> ```

## 実行手順

### 1. 変換スクリプトの実行

```bash
<workspace>/ndlocr-lite/.venv/bin/python <workspace>/.agents/skills/scan-pdf-to-searchable/scripts/convert.py \
    --input <入力スキャンPDFパス> \
    --output <出力検索可能PDFパス> \
    --ndlocr-dir <workspace>/ndlocr-lite/src \
    --dpi 300
```

**引数:**

| 引数 | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `--input` | ✅ | — | 入力スキャンPDFのパス |
| `--output` | ✅ | — | 出力先の検索可能PDFのパス |
| `--ndlocr-dir` | — | `<workspace>/ndlocr-lite/src` | ndlocr-liteの`src`ディレクトリのパス |
| `--dpi` | — | `300` | PDF→画像変換のDPI（高いほど精度↑、速度↓） |

### 2. 処理の流れ

```
入力PDF
  ↓ pypdfium2 (各ページを画像化)
一時PNG画像
  ↓ ndlocr-lite CLI (OCR実行)
OCR結果JSON (boundingBox + text)
  ↓ reportlab (透明テキストレイヤー作成)
オーバーレイPDF
  ↓ pypdf (元PDFと合成)
検索可能PDF
```

### 3. 出力結果の確認

- 出力PDFをPDFビューアで開き、テキスト選択（⌘+A）や検索（⌘+F）ができることを確認
- 見た目は元のスキャンPDFと同一（透明テキストのため視覚的差異なし）
