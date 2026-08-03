#!/usr/bin/env python3
from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GEN = Path("/home/byron/.codex/generated_images/019fbc65-17be-7140-ba1f-b06d839e7bbd")
OUT = ROOT / "static" / "hivelord_pack"


def edge_connected_background_to_alpha(img: Image.Image, tolerance: int = 24) -> Image.Image:
    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size

    corners = [
        px[0, 0][:3],
        px[w - 1, 0][:3],
        px[0, h - 1][:3],
        px[w - 1, h - 1][:3],
    ]
    target = tuple(sum(c[i] for c in corners) // len(corners) for i in range(3))

    seen = [[False] * h for _ in range(w)]
    q: deque[tuple[int, int]] = deque()

    def is_bg(rgb: tuple[int, int, int]) -> bool:
        return all(abs(rgb[i] - target[i]) <= tolerance for i in range(3))

    for x in range(w):
        for y in (0, h - 1):
            if not seen[x][y] and is_bg(px[x, y][:3]):
                seen[x][y] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[x][y] and is_bg(px[x, y][:3]):
                seen[x][y] = True
                q.append((x, y))

    while q:
        x, y = q.popleft()
        r, g, b, a = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny] and is_bg(px[nx, ny][:3]):
                seen[nx][ny] = True
                q.append((nx, ny))
    return rgba


def crop_alpha_bounds(img: Image.Image, pad: int = 12) -> Image.Image:
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(img.width, right + pad)
    bottom = min(img.height, bottom + pad)
    return img.crop((left, top, right, bottom))


def save_grid(
    src_name: str,
    names: list[str],
    cols: int,
    rows: int,
    top_offset: int = 0,
    bottom_trim: int = 0,
    inner_pad: int = 20,
) -> None:
    src = Image.open(GEN / src_name)
    work = src.crop((0, top_offset, src.width, src.height - bottom_trim))
    cell_w = work.width / cols
    cell_h = work.height / rows
    OUT.mkdir(parents=True, exist_ok=True)

    for idx, name in enumerate(names):
        col = idx % cols
        row = idx // cols
        left = int(round(col * cell_w + inner_pad))
        top = int(round(row * cell_h + inner_pad))
        right = int(round((col + 1) * cell_w - inner_pad))
        bottom = int(round((row + 1) * cell_h - inner_pad))
        tile = work.crop((left, top, right, bottom))
        tile = edge_connected_background_to_alpha(tile)
        tile = crop_alpha_bounds(tile)
        tile.save(OUT / f"{name}.png")


def save_metric_grid(
    src_name: str,
    names: list[str],
    cols: int,
    rows: int,
    top_offset: int = 0,
    bottom_trim: int = 0,
    inner_pad_x: int = 24,
    inner_pad_top: int = 18,
    inner_pad_bottom: int = 92,
) -> None:
    src = Image.open(GEN / src_name)
    work = src.crop((0, top_offset, src.width, src.height - bottom_trim))
    cell_w = work.width / cols
    cell_h = work.height / rows
    OUT.mkdir(parents=True, exist_ok=True)

    for idx, name in enumerate(names):
        col = idx % cols
        row = idx // cols
        left = int(round(col * cell_w + inner_pad_x))
        top = int(round(row * cell_h + inner_pad_top))
        right = int(round((col + 1) * cell_w - inner_pad_x))
        bottom = int(round((row + 1) * cell_h - inner_pad_bottom))
        tile = work.crop((left, top, right, bottom))
        tile = edge_connected_background_to_alpha(tile)
        tile = crop_alpha_bounds(tile)
        tile.save(OUT / f"{name}.png")


def save_heroes(src_name: str, names: list[str]) -> None:
    src = Image.open(GEN / src_name)
    top_bar = 120
    work = src.crop((0, top_bar, src.width, src.height))
    cols, rows = 3, 2
    cell_w = work.width / cols
    cell_h = work.height / rows
    OUT.mkdir(parents=True, exist_ok=True)

    for idx, name in enumerate(names):
        col = idx % cols
        row = idx // cols
        left = int(round(col * cell_w + 16))
        top = int(round(row * cell_h + 16))
        right = int(round((col + 1) * cell_w - 16))
        bottom = int(round((row + 1) * cell_h - 16))
        work.crop((left, top, right, bottom)).save(OUT / f"{name}.png")


def main() -> None:
    save_grid(
        "call_MzQUmQAyKGZD038Q3kkJk3yX.png",
        [
            "nav_dashboard",
            "nav_observation",
            "nav_hypotheses",
            "nav_executionlab",
            "nav_validationlab",
            "nav_shadowflight",
            "nav_canary",
            "nav_growth",
            "nav_trades",
            "nav_performance",
            "nav_integrations",
            "nav_logs",
        ],
        cols=4,
        rows=3,
    )
    save_metric_grid(
        "call_Ic3Naw2EkGB2gJz77BMfGEdS.png",
        [
            "metric_portfolio",
            "metric_treasury",
            "metric_pnl_24h",
            "metric_win_rate",
            "metric_total_trades",
            "metric_readiness_gate",
            "metric_swarm_health",
            "metric_market_sentiment",
            "metric_volatility_index",
            "metric_alerts_incidents",
        ],
        cols=5,
        rows=2,
        bottom_trim=90,
    )
    save_heroes(
        "call_t76SQIwmLI7alJ2um8k0LanD.png",
        [
            "hero_dashboard",
            "hero_observation",
            "hero_hypotheses",
            "hero_growth_governor",
            "hero_swarmguard",
            "hero_buzzcoin",
        ],
    )


if __name__ == "__main__":
    main()
