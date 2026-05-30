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

| ツール          | 用途                 | 確認コマンド        |
| --------------- | -------------------- | ------------------- |
| Python 3.10以上 | スクリプト実行       | `python3 --version` |
| uv              | Pythonパッケージ管理 | `uv --version`      |

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

| パッケージ | 用途                              | importチェック                 |
| ---------- | --------------------------------- | ------------------------------ |
| pypdfium2  | PDFページを画像としてレンダリング | `python -c "import pypdfium2"` |
| reportlab  | 透明テキストレイヤーPDFの作成     | `python -c "import reportlab"` |
| pypdf      | 元PDFとオーバーレイPDFの合成      | `python -c "import pypdf"`     |

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

| 引数           | 必須 | デフォルト                    | 説明                                      |
| -------------- | ---- | ----------------------------- | ----------------------------------------- |
| `--input`      | ✅    | —                             | 入力スキャンPDFのパス                     |
| `--output`     | ✅    | —                             | 出力先の検索可能PDFのパス                 |
| `--ndlocr-dir` | —    | `<workspace>/ndlocr-lite/src` | ndlocr-liteの`src`ディレクトリのパス      |
| `--dpi`        | —    | `300`                         | PDF→画像変換のDPI（高いほど精度↑、速度↓） |

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

### 3. 出力結果の検証（必須）

> **⚠️ WARNING**: 変換スクリプトが正常終了しても、テキスト埋め込みが一部ページで失敗している場合があります。
> 過去の事例では、PyPDFの`merge_page()`でページ間のリソース共有参照が原因で、16ページ中14ページでテキストが埋め込まれなかったケースがありました。
> **必ず以下の自動検証を実行し、全ページの埋め込み成功を確認してください。**

#### 3-1. 自動検証スクリプト（必須実行）

変換完了後、以下のワンライナーを実行して全ページにテキストが正しく埋め込まれているか検証してください:

```bash
<workspace>/ndlocr-lite/.venv/bin/python -c "
from pypdf import PdfReader

pdf_path = '<出力検索可能PDFパス>'
reader = PdfReader(pdf_path)
total = len(reader.pages)
ok = 0
ng = 0
ng_pages = []
for i, page in enumerate(reader.pages):
    text = page.extract_text() or ''
    char_count = len(text.strip())
    status = '✅' if char_count > 0 else '❌'
    if char_count > 0:
        ok += 1
    else:
        ng += 1
        ng_pages.append(i + 1)
    print(f'  Page {i+1:3d}: {status} ({char_count:5d} chars)')

print()
print(f'結果: ✅ {ok}/{total} ページ成功, ❌ {ng}/{total} ページ失敗')
if ng_pages:
    print(f'失敗ページ: {ng_pages}')
    print('⚠️ テキスト埋め込みに失敗したページがあります。再変換が必要です。')
else:
    print('🎉 全ページにテキストが正しく埋め込まれています。')
"
```

#### 3-2. 検証結果の判定

| 結果           | 対応                                                                                                                     |
| -------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 全ページ `✅`   | 正常完了。手動確認へ進む                                                                                                 |
| 一部ページ `❌` | **再変換が必要**。`convert.py` の `merge_overlay` 関数を確認し、ページ間のリソース共有参照問題が再発していないか調査する |
| 全ページ `❌`   | OCR処理自体が失敗している可能性あり。ndlocr-liteの出力ログを確認する                                                     |

#### 3-3. 手動確認

- 出力PDFをPDFビューアで開き、テキスト選択（⌘+A）や検索（⌘+F）ができることを確認
- 見た目は元のスキャンPDFと同一（透明テキストのため視覚的差異なし）
