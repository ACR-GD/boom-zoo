"""ROM patchers for Boom Zoo (Taiwan) -> English translation with VWF typography."""

from pathlib import Path
import struct
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from boom_rom import (
    SpaceAllocator,
    pack_bg_tilemap,
    pack_gfx_block,
    pack_spr_tilemap,
    unpack_bg_tilemap,
    unpack_gfx_block,
    unpack_spr_tilemap,
)
from d222 import decompress_d222, encode_d222_best
from vwf import (
    BitmapFont,
    Grid2D,
    TileBankAllocator,
    render_text_mask,
    slice_canvas_to_words,
    style_bevel_banner,
    style_carved_banner,
    style_drop_shadow,
    style_outlined,
    style_solid,
)


def _find_u32_ptrs(rom: bytearray, target: int, start: int = 0, end: int = 0x080000) -> List[int]:
    """Find all 2-byte-aligned 32-bit big-endian pointers equal to `target` in `rom[start:end]`."""
    needle = struct.pack(">I", target)
    hits: List[int] = []
    pos = start
    while pos <= end - 4:
        if rom[pos : pos + 4] == needle:
            hits.append(pos)
        pos += 2
    return hits


def _write_d222_relocated(
    rom: bytearray,
    alloc: SpaceAllocator,
    orig_off: int,
    payload: bytes,
    ptr_locs: Sequence[int],
    label: str,
) -> Tuple[int, int, int]:
    """Compress `payload` via D222, allocate in expanded ROM, and update 32-bit pointers."""
    dec_orig, orig_end = decompress_d222(rom, orig_off)
    orig_comp_len = orig_end - orig_off
    for loc in ptr_locs:
        cur = struct.unpack_from(">I", rom, loc)[0]
        if cur != orig_off:
            raise AssertionError(
                f"{label}: expected pointer 0x{orig_off:06X} at 0x{loc:06X}, found 0x{cur:06X}"
            )

    comp = encode_d222_best(payload)
    new_off = alloc.allocate(len(comp), label, align=2)
    rom[new_off : new_off + len(comp)] = comp
    for loc in ptr_locs:
        struct.pack_into(">I", rom, loc, new_off)
        alloc.record_patch(loc, loc + 4, f"{label}_ptr@0x{loc:06X}")
    return new_off, len(comp), orig_comp_len


def _patch_u16(rom: bytearray, alloc: SpaceAllocator, addr: int, val: int, label: str) -> None:
    struct.pack_into(">H", rom, addr, val & 0xFFFF)
    alloc.record_patch(addr, addr + 2, label)


def _read_spr_lut(rom: bytes, lut_off: int) -> Tuple[int, int, List[int]]:
    lut_start, lut_cnt = struct.unpack_from(">HH", rom, lut_off)
    d2_list = list(struct.unpack_from(f">{lut_cnt}H", rom, lut_off + 4))
    return lut_start, lut_cnt, d2_list


def _spr_frame_slices(lut_start: int, d2_list: Sequence[int], mwords: Sequence[int]) -> Dict[int, List[int]]:
    slices: Dict[int, List[int]] = {}
    woff = 0
    for j, d2 in enumerate(d2_list):
        fid = lut_start + j
        slices[fid] = list(mwords[woff : woff + d2])
        woff += d2
    return slices


def _rebuild_spr_map(lut_start: int, lut_cnt: int, slices: Dict[int, List[int]]) -> List[int]:
    out: List[int] = []
    for j in range(lut_cnt):
        out.extend(slices[lut_start + j])
    return out


def _spr_free_tiles(
    nt: int,
    slices: Dict[int, List[int]],
    target_fids: Set[int],
    extra_keep: Iterable[int] = (),
) -> List[int]:
    used_target: Set[int] = set()
    used_other: Set[int] = {0} | set(extra_keep)
    for fid, words in slices.items():
        tset = {w & 0x3FF for w in words if (w & 0x3FF) < nt}
        if fid in target_fids:
            used_target |= tset
        else:
            used_other |= tset
    return sorted(set(range(nt)) - used_other)


def _composite_over_bg(fg_canvas: Grid2D, bg_tile: Grid2D, cols: int, rows: int) -> Grid2D:
    """Replace 0 pixels in `fg_canvas` with tiled 8x8 `bg_tile` pixels."""
    out: Grid2D = []
    for y in range(rows * 8):
        bg_row = bg_tile[y & 7]
        fg_row = fg_canvas[y]
        out.append([fg_row[x] if fg_row[x] != 0 else bg_row[x & 7] for x in range(cols * 8)])
    return out


def patch_title_sprites(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch Title subtitle ('BOOM BOOM ZOO') and menu ('1P GAME', 'VS MODE', 'PASSWORD')."""
    lut_off = 0x01EC28
    map_orig, map_ref = 0x01EC78, 0x01D29A
    gfx_orig, gfx_ref = 0x025EF6, 0x0234EE

    lut_start, lut_cnt, d2_list = _read_spr_lut(rom, lut_off)
    mwords = unpack_spr_tilemap(decompress_d222(rom, map_orig)[0])
    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    nt = len(tiles)
    slices = _spr_frame_slices(lut_start, d2_list, mwords)

    target_fids = set(range(19, 29))
    free_indices = _spr_free_tiles(nt, slices, target_fids)
    tba = TileBankAllocator(tiles, free_indices)

    # 1. Subtitle: fid=19 ("BOOM"), fid=20 ("ZOO"), fid=21..22 blank (pal 0, fg=2, drop shadow=14)
    w_boom, w_zoo = trans["title"]["subtitle_words"]
    disp = fonts["display"]
    for fid, word in ((19, w_boom), (20, w_zoo)):
        mask = render_text_mask(disp, word, tracking=2)
        canvas = style_drop_shadow(
            mask, 32, 24, fg=2, shadow=14, bg=0, shadow_deltas=((0, 1), (0, 2)), y_off=0
        )
        slices[fid] = slice_canvas_to_words(canvas, pal=0, allocator=tba, allow_flip=True, zero_word_if_all=0)
    slices[21] = [0] * 12
    slices[22] = [0] * 12

    # Reposition State 0 subtitle objects to center "BOOM  BOOM  ZOO" cleanly under the logo
    _patch_u16(rom, alloc, 0x00C876, 0x0048, "title_sub1_x")
    _patch_u16(rom, alloc, 0x00C878, 0x0049, "title_sub1_y")
    _patch_u16(rom, alloc, 0x00C888, 0x0070, "title_sub2_x")
    _patch_u16(rom, alloc, 0x00C88A, 0x0049, "title_sub2_y")
    _patch_u16(rom, alloc, 0x00C89A, 0x0094, "title_sub3_x")
    _patch_u16(rom, alloc, 0x00C89C, 0x0049, "title_sub3_y")

    # 2. Menu options: widen OAM (0x2002 4x2 -> 0x2003 8x2) and TitleLUT d2 (8 -> 16)
    oam_addrs = (0x01B370, 0x01B378, 0x01B380, 0x01B388, 0x01B390, 0x01B398)
    for idx, a in enumerate(oam_addrs):
        _patch_u16(rom, alloc, a + 2, 0x2003, f"title_menu_oam_w1_{23 + idx}")
    for i, fid in enumerate(range(23, 29)):
        d2_list[fid - lut_start] = 16
        _patch_u16(rom, alloc, lut_off + 4 + (fid - lut_start) * 2, 16, f"title_menu_d2_{fid}")

    menu_labels = trans["title"]["menu"]
    for idx, label in enumerate(menu_labels):
        fid_norm = 23 + idx * 2
        fid_blink = fid_norm + 1
        mask = render_text_mask(disp, label, tracking=1, space_w=3)
        canvas = style_solid(mask, 64, 16, fg=13, bg=0, x_off=0, y_off=1)
        words_norm = slice_canvas_to_words(canvas, pal=3, allocator=tba, allow_flip=True, zero_word_if_all=0)
        words_blink = [((w & 0x0FFF) | (4 << 12)) if (w & 0x3FF) != 0 else 0 for w in words_norm]
        slices[fid_norm] = words_norm
        slices[fid_blink] = words_blink

    # Shift menu options & cursor 8px left so "PASSWORD" clears right edge cleanly while cursor clears porthole
    _patch_u16(rom, alloc, 0x00C8D4, 0x00C8, "title_menu_x0")
    _patch_u16(rom, alloc, 0x00C91C, 0x00C8, "title_menu_x1")
    _patch_u16(rom, alloc, 0x00C956, 0x00C8, "title_menu_x2")
    _patch_u16(rom, alloc, 0x00C994, 0x00B8, "title_cursor_x")

    new_mwords = _rebuild_spr_map(lut_start, lut_cnt, slices)
    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_spr_tilemap(new_mwords), [map_ref], "title_spr_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), [gfx_ref], "title_spr_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def patch_char_select_1p(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch 1P Character Select wooden sign BG ('SELECT FIGHTER') and restore bottom flowers."""
    gfx_orig, gfx_ref = 0x043CA6, 0x0097B6
    map_orig, map_ref = 0x043B90, 0x0097D6

    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    mwords = unpack_bg_tilemap(decompress_d222(rom, map_orig)[0])
    nt = len(tiles)

    # Compute tiles used ONLY in r=7..9, c=8..23, while preserving plank 0x22 and flower tiles 0x1D, 0x1E
    in_rect: Set[int] = set()
    out_rect: Set[int] = {0, 0x1D, 0x1E, 0x22}
    for r in range(30):
        for c in range(32):
            t = mwords[r * 32 + c] & 0x3FF
            if 7 <= r <= 9 and 8 <= c <= 23:
                in_rect.add(t)
            else:
                out_rect.add(t)
    free_indices = sorted(set(range(nt)) - out_rect)
    tba = TileBankAllocator(tiles, free_indices)

    # Restore all 8 red flowers along row 9 and plain wood plank along rows 7..8
    flower_pair = (0xD01E, 0xD01D)
    for c in range(8, 24):
        mwords[7 * 32 + c] = 0xD022
        mwords[8 * 32 + c] = 0xD022
        mwords[9 * 32 + c] = flower_pair[(c - 8) & 1]

    header = trans["char_select_1p"]["header"]
    mask = render_text_mask(fonts["display"], header, tracking=1, space_w=4)
    fg_canvas = style_outlined(mask, 96, 16, fg=14, outline=1, bg=0, neighbors=4, y_off=1)
    composited = _composite_over_bg(fg_canvas, tiles[0x22], cols=12, rows=2)
    text_words = slice_canvas_to_words(composited, pal=13, allocator=tba, allow_flip=True)
    for r in range(2):
        for c in range(12):
            mwords[(7 + r) * 32 + (10 + c)] = text_words[r * 12 + c]

    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_bg_tilemap(mwords), [map_ref], "charsel_bg_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), [gfx_ref], "charsel_bg_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def patch_hud_sprites(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch HUD sprites ('JOIN IN!', 'PUSH START', 'PAUSED!', 'HURRY UP!') and update all 44 ptr pairs."""
    lut_off = 0x01E7F6
    map_orig = 0x01E868
    gfx_orig = 0x024C9C

    map_refs = _find_u32_ptrs(rom, map_orig, 0x01D280, 0x01E500)
    gfx_refs = _find_u32_ptrs(rom, gfx_orig, 0x023480, 0x023E00)
    if len(map_refs) != 44 or len(gfx_refs) != 44:
        raise AssertionError(
            f"Expected 44 HUD map/gfx ptrs, found {len(map_refs)} / {len(gfx_refs)}"
        )

    lut_start, lut_cnt, d2_list = _read_spr_lut(rom, lut_off)
    mwords = unpack_spr_tilemap(decompress_d222(rom, map_orig)[0])
    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    nt = len(tiles)
    slices = _spr_frame_slices(lut_start, d2_list, mwords)

    # Preserve fid=248 (gold '!') & fid=254 (white blink '!') tiles so target replacements exclude them
    bang_keep = {w & 0x3FF for w in slices[248] + slices[254]}
    target_fids = set(range(237, 255)) - {248, 254}
    free_indices = _spr_free_tiles(nt, slices, target_fids, extra_keep=bang_keep)
    tba = TileBankAllocator(tiles, free_indices)

    disp = fonts["display"]
    banner = fonts["banner"]

    # fid=237: "JOIN IN!" (8x2 = 64x16, solid white fg=4 on 0, pal 13)
    m_join = render_text_mask(disp, trans["hud"]["join_in"], tracking=1, space_w=4)
    c_join = style_solid(m_join, 64, 16, fg=4, bg=0)
    slices[237] = slice_canvas_to_words(c_join, pal=13, allocator=tba, allow_flip=True, zero_word_if_all=0)

    # fid=238: "PUSH START" (8x2 = 64x16, solid white fg=4 on 0, pal 13)
    m_start = render_text_mask(disp, trans["hud"]["push_start"], tracking=1, space_w=3)
    c_start = style_solid(m_start, 64, 16, fg=4, bg=0)
    slices[238] = slice_canvas_to_words(c_start, pal=13, allocator=tba, allow_flip=True, zero_word_if_all=0)

    # fid=239..242: "PAUSED" across 4 sprites spaced +24px apart (total 96x24 non-overlapping + fid=248 '!')
    m_pause = render_text_mask(banner, trans["hud"]["paused"], tracking=3, scale_x=1.5)
    c_pause = style_bevel_banner(
        m_pause,
        96,
        24,
        outline_col=6,
        top_fill=10,
        bot_fill=8,
        bg_col=0,
        x_off=96 - len(m_pause[0]) - 5,
    )
    for i, fid in enumerate(range(239, 243)):
        chunk = [row[i * 24 : (i + 1) * 24] for row in c_pause]
        w3x3 = slice_canvas_to_words(chunk, pal=13, allocator=tba, allow_flip=True, zero_word_if_all=0)
        padded_4x3: List[int] = []
        for r in range(3):
            padded_4x3.extend(w3x3[r * 3 : (r + 1) * 3])
            padded_4x3.append(0)
        slices[fid] = padded_4x3

    # fid=243..247 (gold) & fid=249..253 (white blink): "HURRY UP" across 5 sprites spaced +24px (120x24 + '!')
    m_hurry = render_text_mask(banner, trans["hud"]["hurry_up"], tracking=2, space_w=6, scale_x=1.5)
    for base_fid, top_c, bot_c in ((243, 10, 8), (249, 4, 13)):
        c_hurry = style_bevel_banner(
            m_hurry,
            120,
            24,
            outline_col=6,
            top_fill=top_c,
            bot_fill=bot_c,
            bg_col=0,
            x_off=120 - len(m_hurry[0]) - 5,
        )
        for i in range(5):
            chunk = [row[i * 24 : (i + 1) * 24] for row in c_hurry]
            w3x3 = slice_canvas_to_words(chunk, pal=13, allocator=tba, allow_flip=True, zero_word_if_all=0)
            padded_4x3 = []
            for r in range(3):
                padded_4x3.extend(w3x3[r * 3 : (r + 1) * 3])
                padded_4x3.append(0)
            slices[base_fid + i] = padded_4x3

    new_mwords = _rebuild_spr_map(lut_start, lut_cnt, slices)
    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_spr_tilemap(new_mwords), map_refs, "hud_spr_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), gfx_refs, "hud_spr_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def patch_continue_sprites(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch Continue speech bubble fid=6 ('CONTINUE?' / 'NO' / 'YES') preserving outer border."""
    lut_off = 0x022850
    map_orig, map_ref = 0x022862, 0x01D304
    gfx_orig, gfx_ref = 0x03B3DC, 0x02351E

    lut_start, lut_cnt, d2_list = _read_spr_lut(rom, lut_off)
    mwords = unpack_spr_tilemap(decompress_d222(rom, map_orig)[0])
    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    nt = len(tiles)
    slices = _spr_frame_slices(lut_start, d2_list, mwords)

    # Preserve outer border tiles used in rows 0, 7, 8 and cols 0, 7 of fid=6
    f6 = slices[6]
    border_keep: Set[int] = set()
    for r in range(9):
        for c in range(8):
            if r in (0, 7, 8) or c in (0, 7):
                border_keep.add(f6[r * 8 + c] & 0x3FF)

    free_indices = _spr_free_tiles(nt, slices, {6}, extra_keep=border_keep)
    tba = TileBankAllocator(tiles, free_indices)

    # Build fresh 48x48 bubble interior (cols 1..6, rows 1..6) filled with 15 (white) and text 14 (slate blue)
    interior: Grid2D = [[15] * 48 for _ in range(48)]

    def stamp_on_interior(mask: Grid2D, x_off: Optional[int], y_off: int) -> None:
        mw = len(mask[0])
        if x_off is None:
            x_off = (48 - mw) // 2
        for y, row in enumerate(mask):
            dy = y_off + y
            if 0 <= dy < 48:
                for x, on in enumerate(row):
                    if on and 0 <= x_off + x < 48:
                        interior[dy][x_off + x] = 14

    m_prompt = render_text_mask(fonts["body"], trans["continue"]["prompt"], tracking=0)
    m_no = render_text_mask(fonts["display"], trans["continue"]["no"], tracking=1)
    m_yes = render_text_mask(fonts["display"], trans["continue"]["yes"], tracking=1)

    stamp_on_interior(m_prompt, x_off=None, y_off=-2)  # ink y=3..9 -> interior y=1..7 (single tile row)
    stamp_on_interior(m_no, x_off=16, y_off=16)       # local x=16 -> fid=6 x=24 (clears cursor at x=8..22)
    stamp_on_interior(m_yes, x_off=16, y_off=32)      # local x=16 -> fid=6 x=24

    inner_words = slice_canvas_to_words(interior, pal=13, allocator=tba, allow_flip=True)
    for r in range(6):
        for c in range(6):
            f6[(r + 1) * 8 + (c + 1)] = inner_words[r * 6 + c]
    slices[6] = f6

    new_mwords = _rebuild_spr_map(lut_start, lut_cnt, slices)
    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_spr_tilemap(new_mwords), [map_ref], "cont_spr_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), [gfx_ref], "cont_spr_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def patch_vs_setup_bg(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch VS Setup BG ('PLAYERS', 'CHARACTERS', 'ROUNDS')."""
    gfx_orig, gfx_ref = 0x049ACC, 0x00B27E
    map_orig, map_ref = 0x04A076, 0x00B29E

    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    mwords = unpack_bg_tilemap(decompress_d222(rom, map_orig)[0])
    nt = len(tiles)

    bands = ((5, 7, 1, 30), (12, 14, 1, 30), (20, 22, 1, 30))
    out_rect: Set[int] = {0}
    for r in range(30):
        for c in range(32):
            if not any(r0 <= r <= r1 and c0 <= c <= c1 for (r0, r1, c0, c1) in bands):
                out_rect.add(mwords[r * 32 + c] & 0x3FF)
    free_indices = sorted(set(range(nt)) - out_rect)
    tba = TileBankAllocator(tiles, free_indices)

    for r0, r1, c0, c1 in bands:
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                mwords[r * 32 + c] = 0x0000

    banner = fonts["banner"]
    placements = (
        (trans["vs_setup"]["players"], 5, 10, 12),
        (trans["vs_setup"]["characters"], 12, 8, 16),
        (trans["vs_setup"]["rounds"], 20, 10, 12),
    )
    for label, r0, c0, col_w in placements:
        mask = render_text_mask(banner, label, tracking=2)
        canvas = style_carved_banner(mask, col_w * 8, 24, fill_col=1, outline_col=2, top_col=4, bg_col=0)
        words = slice_canvas_to_words(canvas, pal=13, allocator=tba, allow_flip=True, zero_word_if_all=0)
        for dr in range(3):
            for dc in range(col_w):
                mwords[(r0 + dr) * 32 + (c0 + dc)] = words[dr * col_w + dc]

    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_bg_tilemap(mwords), [map_ref], "vssetup_bg_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), [gfx_ref], "vssetup_bg_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def patch_vs_stage_select_spr(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch VS Stage Select sprite fid=0 ('SELECT STAGE', keeping width <= 104px to clear digit)."""
    lut_off = 0x023158
    map_orig, map_ref = 0x023184, 0x01D320
    gfx_orig, gfx_ref = 0x03E5CE, 0x023536

    lut_start, lut_cnt, d2_list = _read_spr_lut(rom, lut_off)
    mwords = unpack_spr_tilemap(decompress_d222(rom, map_orig)[0])
    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    nt = len(tiles)
    slices = _spr_frame_slices(lut_start, d2_list, mwords)

    free_indices = _spr_free_tiles(nt, slices, {0})
    tba = TileBankAllocator(tiles, free_indices)

    mask = render_text_mask(fonts["banner"], trans["vs_stage_select"]["header"], tracking=1, space_w=4)
    canvas = style_carved_banner(
        mask, 128, 24, fill_col=1, outline_col=2, top_col=4, bg_col=0, x_off=0
    )
    slices[0] = slice_canvas_to_words(
        canvas, pal=13, allocator=tba, allow_flip=True, zero_word_if_all=0
    )

    new_mwords = _rebuild_spr_map(lut_start, lut_cnt, slices)
    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_spr_tilemap(new_mwords), [map_ref], "vsstg_spr_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), [gfx_ref], "vsstg_spr_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def patch_vs_results_bg(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, object]:
    """Patch VS Results BG ('RESULTS' at r=4..6) while preserving 0x04A5B2 ('VICTOR!') tiles."""
    gfx_orig, gfx_refs = 0x04A1CA, [0x00B814, 0x00B92A]
    map_orig, map_ref = 0x04A4FA, 0x00B834
    victor_map_orig = 0x04A5B2

    tiles = unpack_gfx_block(decompress_d222(rom, gfx_orig)[0])
    mwords = unpack_bg_tilemap(decompress_d222(rom, map_orig)[0])
    victor_words = unpack_bg_tilemap(decompress_d222(rom, victor_map_orig)[0])
    nt = len(tiles)

    out_rect: Set[int] = {0, 0x25} | {w & 0x3FF for w in victor_words}
    for r in range(30):
        for c in range(32):
            if not (4 <= r <= 6 and 11 <= c <= 21):
                out_rect.add(mwords[r * 32 + c] & 0x3FF)
    free_indices = sorted(set(range(nt)) - out_rect)
    tba = TileBankAllocator(tiles, free_indices)

    for r in range(4, 7):
        for c in range(11, 22):
            mwords[r * 32 + c] = 0xD025

    mask = render_text_mask(fonts["banner"], trans["vs_results"]["header"], tracking=2)
    canvas = style_carved_banner(
        mask, 72, 24, fill_col=1, outline_col=2, top_col=4, bg_col=9
    )
    words = slice_canvas_to_words(canvas, pal=13, allocator=tba, allow_flip=True)
    for dr in range(3):
        for dc in range(9):
            mwords[(4 + dr) * 32 + (12 + dc)] = words[dr * 9 + dc]

    map_off, map_c, map_oc = _write_d222_relocated(
        rom, alloc, map_orig, pack_bg_tilemap(mwords), [map_ref], "vsres_bg_map"
    )
    gfx_off, gfx_c, gfx_oc = _write_d222_relocated(
        rom, alloc, gfx_orig, pack_gfx_block(tiles), gfx_refs, "vsres_bg_gfx"
    )
    return {
        "nt": nt,
        "free_avail": len(free_indices),
        "tiles_used": len(tba.allocated),
        "map_off": map_off,
        "map_comp": (map_oc, map_c),
        "gfx_off": gfx_off,
        "gfx_comp": (gfx_oc, gfx_c),
    }


def apply_all_patches(
    rom: bytearray,
    alloc: SpaceAllocator,
    fonts: Dict[str, BitmapFont],
    trans: dict,
) -> Dict[str, Dict[str, object]]:
    """Run all 7 localized asset patchers in order and return per-target statistics."""
    return {
        "title_sprites": patch_title_sprites(rom, alloc, fonts, trans),
        "char_select_1p": patch_char_select_1p(rom, alloc, fonts, trans),
        "hud_sprites": patch_hud_sprites(rom, alloc, fonts, trans),
        "continue_sprites": patch_continue_sprites(rom, alloc, fonts, trans),
        "vs_setup_bg": patch_vs_setup_bg(rom, alloc, fonts, trans),
        "vs_stage_select_spr": patch_vs_stage_select_spr(rom, alloc, fonts, trans),
        "vs_results_bg": patch_vs_results_bg(rom, alloc, fonts, trans),
    }
