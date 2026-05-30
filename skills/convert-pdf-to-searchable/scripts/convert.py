#!/usr/bin/env python3
"""
scan-pdf-to-searchable: スキャンPDFをndlocr-liteでOCRし、
透明テキストを埋め込んで検索可能PDFに変換するスクリプト。

処理フロー:
1. PDFの各ページをpypdfium2で画像化 (PNG)
2. ndlocr-lite CLIでOCR実行 (JSON出力)
3. OCR結果JSONからboundingBoxとtextを取得
4. ReportLabで透明テキストレイヤーPDFを作成
5. PyPDFで元PDFとオーバーレイPDFを合成
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# 日本語フォント（ReportLab内蔵CIDフォント）を登録
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))


def render_pdf_pages_to_images(pdf_path: str, output_dir: str, dpi: int = 300) -> list[dict]:
    """PDFの各ページを画像としてレンダリングし、PNGファイルとして保存する。

    Args:
        pdf_path: 入力PDFのパス
        output_dir: 画像の保存先ディレクトリ
        dpi: レンダリングDPI

    Returns:
        各ページの情報を含む辞書のリスト
        [{"page_index": int, "image_path": str, "pdf_width_pt": float, "pdf_height_pt": float}]
    """
    pdf = pdfium.PdfDocument(pdf_path)
    pages_info = []
    scale = dpi / 72  # PDFは72dpiベース

    for i in range(len(pdf)):
        page = pdf[i]
        # PDFページのサイズ（ポイント単位）を取得
        pdf_width_pt = page.get_width()
        pdf_height_pt = page.get_height()

        # 画像としてレンダリング
        pil_img = page.render(scale=scale).to_pil()
        img_filename = f"page_{i:04d}.png"
        img_path = os.path.join(output_dir, img_filename)
        pil_img.save(img_path)

        pages_info.append({
            "page_index": i,
            "image_path": img_path,
            "image_filename": img_filename,
            "pdf_width_pt": pdf_width_pt,
            "pdf_height_pt": pdf_height_pt,
            "img_width_px": pil_img.width,
            "img_height_px": pil_img.height,
        })
        print(f"  [INFO] Page {i + 1}/{len(pdf)}: {pil_img.width}x{pil_img.height}px (PDF: {pdf_width_pt:.1f}x{pdf_height_pt:.1f}pt)")

    return pages_info


def run_ndlocr_ocr(image_path: str, output_dir: str, ndlocr_src_dir: str) -> str:
    """ndlocr-lite CLIを実行してOCRを行う。

    Args:
        image_path: 入力画像のパス（単一画像）
        output_dir: OCR結果の出力先ディレクトリ
        ndlocr_src_dir: ndlocr-liteのsrcディレクトリパス

    Returns:
        出力されたJSONファイルのパス
    """
    ocr_script = os.path.join(ndlocr_src_dir, "ocr.py")
    if not os.path.isfile(ocr_script):
        raise FileNotFoundError(f"ndlocr-lite の ocr.py が見つかりません: {ocr_script}")

    cmd = [
        sys.executable,
        ocr_script,
        "--sourceimg", image_path,
        "--output", output_dir,
        "--json-only",
    ]

    print(f"  [INFO] Running ndlocr-lite: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=ndlocr_src_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  [ERROR] ndlocr-lite stderr:\n{result.stderr}")
        raise RuntimeError(f"ndlocr-lite OCR failed with return code {result.returncode}")

    if result.stdout:
        # ndlocr-liteの進捗出力を表示
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")

    # 出力JSONファイルのパスを特定
    stem = Path(image_path).stem
    json_path = os.path.join(output_dir, f"{stem}.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"OCR結果JSONが見つかりません: {json_path}")

    return json_path


def parse_ocr_json(json_path: str) -> list[dict]:
    """ndlocr-liteのOCR結果JSONを解析し、正規化されたOCRアイテムのリストを返す。

    Args:
        json_path: ndlocr-lite出力JSONのパス

    Returns:
        OCRアイテムのリスト
        [{"text": str, "bbox": (min_x, min_y, max_x, max_y)}]
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    # contents は [[{...}, {...}, ...]] 形式（ページ単位の配列）
    for page_contents in data.get("contents", []):
        for entry in page_contents:
            text = entry.get("text", "").strip()
            if not text:
                continue

            # boundingBox: [[x1,y1],[x1,y2],[x2,y1],[x2,y2]]
            bbox_points = entry.get("boundingBox", [])
            if len(bbox_points) < 4:
                continue

            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            items.append({
                "text": text,
                "bbox": (min(xs), min(ys), max(xs), max(ys)),
            })

    return items


def create_overlay_pdf(
    page_width_pt: float,
    page_height_pt: float,
    ocr_items: list[dict],
    img_width_px: int,
    img_height_px: int,
) -> bytes:
    """OCR結果をもとに透明テキストレイヤーPDFを作成する。

    Args:
        page_width_pt: PDFページの幅（ポイント）
        page_height_pt: PDFページの高さ（ポイント）
        ocr_items: parse_ocr_json()の出力
        img_width_px: OCR対象画像の幅（ピクセル）
        img_height_px: OCR対象画像の高さ（ピクセル）

    Returns:
        オーバーレイPDFのバイト列
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width_pt, page_height_pt))

    # 完全透明に設定
    c.setFillAlpha(0.0)

    # 画像座標（px）→ PDF座標（pt）のスケールファクター
    scale_x = page_width_pt / img_width_px
    scale_y = page_height_pt / img_height_px

    for item in ocr_items:
        x1_px, y1_px, x2_px, y2_px = item["bbox"]
        text = item["text"]

        # 画像座標 → PDF座標に変換
        x1_pt = x1_px * scale_x
        x2_pt = x2_px * scale_x
        y1_pt = y1_px * scale_y
        y2_pt = y2_px * scale_y

        # バウンディングボックスの幅と高さ（PDF座標）
        box_width_pt = x2_pt - x1_pt
        box_height_pt = y2_pt - y1_pt

        # フォントサイズを矩形の高さに合わせる
        fontsize = max(4, box_height_pt * 0.85)
        c.setFont("HeiseiKakuGo-W5", fontsize)

        # PDF座標は左下原点、画像座標は左上原点 → Y座標を反転
        # baseline_y = ページ高さ - テキスト矩形の下端(y2)
        baseline_y = page_height_pt - y2_pt

        # テキストの幅を計算し、水平方向にフィットさせる
        text_width = c.stringWidth(text, "HeiseiKakuGo-W5", fontsize)
        if text_width > 0 and box_width_pt > 0:
            h_scale = (box_width_pt / text_width) * 100  # パーセント
        else:
            h_scale = 100

        c.saveState()
        c.translate(x1_pt, baseline_y)
        c.scale(h_scale / 100.0, 1.0)
        c.drawString(0, 0, text)
        c.restoreState()

    c.save()
    return buf.getvalue()


def merge_overlay(
    original_pdf_path: str,
    overlay_bytes_list: list[bytes],
    output_pdf_path: str,
) -> None:
    """元PDFの各ページにオーバーレイPDFを合成して出力する。

    Args:
        original_pdf_path: 元のPDFパス
        overlay_bytes_list: 各ページのオーバーレイPDFバイト列のリスト
        output_pdf_path: 出力PDFパス
    """
    # NOTE: PdfReaderはページ間で/Resources等の内部オブジェクトを共有参照する。
    # merge_page()が最初のページで共有リソースを変更すると、後続ページの
    # リソースも汚染され、テキスト埋め込みが失われる。
    # これを回避するため、各ページごとにPdfReaderを新規作成して独立させる。
    writer = PdfWriter()
    num_pages = len(PdfReader(original_pdf_path).pages)

    for i in range(num_pages):
        reader = PdfReader(original_pdf_path)
        page = reader.pages[i]
        if i < len(overlay_bytes_list) and overlay_bytes_list[i] is not None:
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes_list[i]))
            overlay_page = overlay_reader.pages[0]
            page.merge_page(overlay_page)
        writer.add_page(page)

    with open(output_pdf_path, "wb") as f:
        writer.write(f)


def convert_pdf(
    input_pdf: str,
    output_pdf: str,
    ndlocr_src_dir: str,
    dpi: int = 300,
) -> None:
    """スキャンPDFを検索可能PDFに変換するメイン処理。

    Args:
        input_pdf: 入力スキャンPDFのパス
        output_pdf: 出力検索可能PDFのパス
        ndlocr_src_dir: ndlocr-liteのsrcディレクトリパス
        dpi: レンダリングDPI
    """
    input_pdf = os.path.abspath(input_pdf)
    output_pdf = os.path.abspath(output_pdf)
    ndlocr_src_dir = os.path.abspath(ndlocr_src_dir)

    if not os.path.isfile(input_pdf):
        raise FileNotFoundError(f"入力PDFが見つかりません: {input_pdf}")

    print(f"[INFO] 入力PDF: {input_pdf}")
    print(f"[INFO] 出力PDF: {output_pdf}")
    print(f"[INFO] ndlocr-lite: {ndlocr_src_dir}")
    print(f"[INFO] DPI: {dpi}")
    print()

    with tempfile.TemporaryDirectory(prefix="scan2searchable_") as tmpdir:
        img_dir = os.path.join(tmpdir, "images")
        ocr_dir = os.path.join(tmpdir, "ocr_results")
        os.makedirs(img_dir, exist_ok=True)
        os.makedirs(ocr_dir, exist_ok=True)

        # Step 1: PDFを画像化
        print("[Step 1/4] PDFページを画像化...")
        pages_info = render_pdf_pages_to_images(input_pdf, img_dir, dpi=dpi)
        print(f"  → {len(pages_info)} ページを画像化しました\n")

        # Step 2-3: 各ページをOCR → 透明テキストレイヤー作成
        overlay_bytes_list = []
        for page_info in pages_info:
            page_idx = page_info["page_index"]
            print(f"[Step 2/4] Page {page_idx + 1}: ndlocr-liteでOCR実行...")

            # OCR実行
            json_path = run_ndlocr_ocr(
                image_path=page_info["image_path"],
                output_dir=ocr_dir,
                ndlocr_src_dir=ndlocr_src_dir,
            )

            # OCR結果解析
            ocr_items = parse_ocr_json(json_path)
            print(f"  → {len(ocr_items)} テキスト領域を検出\n")

            if len(ocr_items) == 0:
                overlay_bytes_list.append(None)
                continue

            # Step 3: 透明テキストレイヤーPDF作成
            print(f"[Step 3/4] Page {page_idx + 1}: 透明テキストレイヤーPDF作成...")
            overlay_bytes = create_overlay_pdf(
                page_width_pt=page_info["pdf_width_pt"],
                page_height_pt=page_info["pdf_height_pt"],
                ocr_items=ocr_items,
                img_width_px=page_info["img_width_px"],
                img_height_px=page_info["img_height_px"],
            )
            overlay_bytes_list.append(overlay_bytes)
            print("  → 完了\n")

        # Step 4: 元PDFとオーバーレイを合成
        print("[Step 4/4] 元PDFとオーバーレイPDFを合成...")
        merge_overlay(input_pdf, overlay_bytes_list, output_pdf)
        print(f"  → 検索可能PDFを出力しました: {output_pdf}\n")

    print("[INFO] 変換完了！")


def main():
    # デフォルトのndlocr-liteパスを算出
    # このスクリプトからの相対パス: ../../ndlocr-lite/src → ワークスペースルート基準
    script_dir = Path(__file__).resolve().parent
    workspace_root = script_dir.parent.parent.parent  # .agents/skills/scan-pdf-to-searchable/scripts/ → workspace root
    default_ndlocr_dir = str(workspace_root / "ndlocr-lite" / "src")

    parser = argparse.ArgumentParser(
        description="スキャンPDFをndlocr-liteでOCRし、透明テキストを埋め込んで検索可能PDFに変換する"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="入力スキャンPDFのパス",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        required=True,
        help="出力検索可能PDFのパス",
    )
    parser.add_argument(
        "--ndlocr-dir",
        type=str,
        default=default_ndlocr_dir,
        help=f"ndlocr-liteのsrcディレクトリパス (default: {default_ndlocr_dir})",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="PDF→画像変換のDPI (default: 300)",
    )

    args = parser.parse_args()
    convert_pdf(
        input_pdf=args.input,
        output_pdf=args.output,
        ndlocr_src_dir=args.ndlocr_dir,
        dpi=args.dpi,
    )


if __name__ == "__main__":
    main()
