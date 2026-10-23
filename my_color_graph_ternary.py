"""
SPIKEハブのカラーセンサー値(R,G,B)を受信し、RGB比率の三角図で表示する。

使い方:
  測定して描画 : python rgb_ternary.py
  保存済みCSV  : python rgb_ternary.py --csv rgb_20261021_170000.csv
  ポート指定   : python rgb_ternary.py --port COM6
  拡大表示     : python rgb_ternary.py --zoom   (点群に合わせて拡大。目盛りは拡大後の値)

受信データは自動でCSVに保存されるので、あとから何度でも描き直せる。
"""
import argparse
import csv
import datetime
import sys

import numpy as np
import matplotlib.pyplot as plt
import ternary

# ====================================================================
# 設定項目
# ====================================================================
COM_PORT = 'COM6'
BAUD_RATE = 115200
BLACK_THRESHOLD = 10   # R,G,Bすべてがこの値以下なら黒として除外
ZOOM_MARGIN = 5.0      # --zoom 時、最小値から引く余白(%)
SCALE = 255            # 三角図の軸の最大値(R+G+Bの比率をこの合計に正規化して表示)
GRID_STEP = 51         # 目盛り・グリッドの間隔(255の約数: 15 / 17 / 51 / 85 など)


# ====================================================================
# データ取得
# ====================================================================
def read_serial(port):
    import serial
    print(f"[{port}] でSPIKEハブからのデータ待機中...")
    rows = []
    try:
        with serial.Serial(port, BAUD_RATE, timeout=2) as ser:
            while True:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                if line == "DONE":
                    break

                # 1件受信するたびに、RGB値をCMDへ表示
                print(f"受信: {line}")

                try:
                    r, g, b = map(int, line.split(','))
                except ValueError:
                    continue

                rows.append((r, g, b))
    except serial.SerialException as e:
        print(f"エラー: {port} を開けませんでした ({e})")
        sys.exit(1)
    print(f"受信完了: {len(rows)} 件")
    return np.array(rows, dtype=float).reshape(-1, 3)


def save_csv(data):
    name = datetime.datetime.now().strftime("rgb_%Y%m%d_%H%M%S.csv")
    with open(name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["R", "G", "B"])
        w.writerows(data.astype(int).tolist())
    print(f"生データを保存しました: {name}")


def load_csv(path):
    data = np.genfromtxt(path, delimiter=",", skip_header=1)
    return np.atleast_2d(data)[:, :3]


# ====================================================================
# 集計
# ====================================================================
def summarize(rgb, ratio):
    print("\n===== 集計結果 =====")
    print(f"有効データ数: {len(rgb)}")
    print("                min     5%     mean    95%     max")
    for i, n in enumerate("RGB"):
        v = rgb[:, i]
        p5, p95 = np.percentile(v, [5, 95])
        print(f"生 {n}      {v.min():7.1f}{p5:7.1f}{v.mean():8.1f}{p95:7.1f}{v.max():7.1f}")
    for i, n in enumerate("RGB"):
        v = ratio[:, i]
        p5, p95 = np.percentile(v, [5, 95])
        print(f"{n}比率(%) {v.min():7.1f}{p5:7.1f}{v.mean():8.1f}{p95:7.1f}{v.max():7.1f}")
    print("====================\n")


# ====================================================================
# 描画
# ====================================================================
def plot(rgb, ratio, zoom):
    # 座標: (R, G, B) -> 右下=Red, 上=Green, 左下=Blue
    # 各軸の値は「R/(R+G+B)×SCALE」なので、3軸の合計は常にSCALE(=255)になる
    if zoom:
        base = np.maximum(0.0, ratio.min(axis=0) - ZOOM_MARGIN)
        mod = np.maximum(0.0, ratio - base)
        s = mod.sum(axis=1)
        keep = s > 0
        rgb, ratio, mod, s = rgb[keep], ratio[keep], mod[keep], s[keep]
        coords = mod / s[:, None] * SCALE
        suffix = "(zoomed)"
    else:
        coords = ratio / 100.0 * SCALE
        suffix = "(true ratio)"

    fig, tax = ternary.figure(scale=SCALE)
    fig.set_size_inches(8, 7.5)
    tax.boundary(linewidth=2.0)
    tax.gridlines(multiple=GRID_STEP, color="blue", linewidth=0.5)
    tax.ticks(axis='lbr', multiple=GRID_STEP, linewidth=1, offset=0.02, tick_formats="%d")

    note = "" if not zoom else "\n(zoom: 軸は拡大後の値)"
    tax.bottom_axis_label(f"Red (/{SCALE}){note}", offset=0.12)
    tax.right_axis_label(f"Green (/{SCALE})", offset=0.14)
    tax.left_axis_label(f"Blue (/{SCALE})", offset=0.14)

    # 点は完全不透明(alpha=1)・輪郭なし。重なっても色が混ざって濃くならない。
    # 明るい点ほど手前に描く(暗い点が明るい点を隠さないようにする)
    colors = np.clip(rgb / 255.0, 0, 1)
    order = np.argsort(rgb.sum(axis=1))
    tax.scatter(coords[order], c=colors[order], s=15,
                edgecolors='none', linewidths=0, alpha=1.0)

    # 範囲(5〜95%)をタイトルに表示
    lo = np.percentile(ratio, 5, axis=0) / 100.0 * SCALE
    hi = np.percentile(ratio, 95, axis=0) / 100.0 * SCALE
    tax.set_title(
        f"RGB Ternary Plot {suffix}\n"
        f"R {lo[0]:.0f}-{hi[0]:.0f}  G {lo[1]:.0f}-{hi[1]:.0f}  B {lo[2]:.0f}-{hi[2]:.0f}  (5-95%, /{SCALE})",
        pad=25)
    tax.clear_matplotlib_ticks()
    tax.get_axes().axis('off')

    # ホバーで実際のRGBと比率を表示(拡大していても常に本当の値)
    proj = np.array([ternary.helpers.project_point(tuple(c)) for c in coords])
    near_sq = (0.022 * SCALE) ** 2

    def format_coord(x, y):
        d = (proj[:, 0] - x) ** 2 + (proj[:, 1] - y) ** 2
        i = int(np.argmin(d))
        if d[i] < near_sq:
            r, g, b = rgb[i].astype(int)
            pr, pg, pb = ratio[i] / 100.0 * SCALE
            return f"RGB=({r},{g},{b})  比率(/{SCALE}) R{pr:.0f} G{pg:.0f} B{pb:.0f}"
        return ""

    tax.get_axes().format_coord = format_coord
    tax.show()   # 軸ラベルの描画もここで行われる


# ====================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=COM_PORT)
    ap.add_argument("--csv", help="保存済みCSVから描画(ハブ不要)")
    ap.add_argument("--zoom", action="store_true", help="点群に合わせて拡大")
    ap.add_argument("--black", type=int, default=BLACK_THRESHOLD, help="黒除外のしきい値")
    args = ap.parse_args()

    if args.csv:
        data = load_csv(args.csv)
    else:
        data = read_serial(args.port)
        if len(data):
            save_csv(data)

    if len(data) == 0:
        print("データがありません。")
        return

    black = np.all(data <= args.black, axis=1)
    print(f"黒として除外: {black.sum()} 件")
    rgb = data[~black]
    total = rgb.sum(axis=1)
    ok = total > 0
    rgb, total = rgb[ok], total[ok]
    if len(rgb) == 0:
        print("黒以外の有効なデータがありません。")
        return

    ratio = rgb / total[:, None] * 100
    summarize(rgb, ratio)
    plot(rgb, ratio, args.zoom)


if __name__ == '__main__':
    main()
