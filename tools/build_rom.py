#!/usr/bin/env python3
"""Build script for Boom Zoo (EN).bin, Boom Zoo (EN).ips, and build/report.txt."""

import hashlib
import json
from pathlib import Path
import sys
from typing import List

TOOLS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TOOLS_DIR.parent
NOTES_DIR = ROOT_DIR / "notes"
BUILD_DIR = ROOT_DIR / "build"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from boom_rom import (
    EXPANDED_ROM_SIZE,
    ORIG_ROM_PATH,
    SpaceAllocator,
    apply_ips,
    byteswap_16,
    load_orig_rom_unswapped,
    save_rom_swapped,
    write_ips,
)
from patchers import apply_all_patches
from vwf import load_fonts


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def build_rom() -> None:
    orig_swapped = ORIG_ROM_PATH.read_bytes()
    orig_sha1 = _sha1(orig_swapped)

    rom = load_orig_rom_unswapped(ORIG_ROM_PATH, expand_1mb=True, pad_byte=0xFF)
    alloc = SpaceAllocator([(len(orig_swapped), EXPANDED_ROM_SIZE)])
    fonts = load_fonts(NOTES_DIR)
    trans = json.loads((NOTES_DIR / "translations_en.json").read_text(encoding="utf-8"))

    stats = apply_all_patches(rom, alloc, fonts, trans)
    alloc.verify_non_overlapping()

    out_bin = BUILD_DIR / "Boom Zoo (EN).bin"
    out_ips = BUILD_DIR / "Boom Zoo (EN).ips"
    out_report = BUILD_DIR / "report.txt"

    save_rom_swapped(bytes(rom), out_bin)
    built_swapped = out_bin.read_bytes()
    write_ips(orig_swapped, built_swapped, out_ips)

    reconstructed = apply_ips(orig_swapped, out_ips)
    if reconstructed != built_swapped:
        raise AssertionError("IPS round-trip verification failed: apply_ips(orig, ips) != built ROM")

    # Confirm source ROM remained completely untouched
    if _sha1(ORIG_ROM_PATH.read_bytes()) != orig_sha1:
        raise AssertionError("Original ROM checksum changed unexpectedly!")

    lines: List[str] = [
        "Boom Zoo (Taiwan) -> English Translation Build Report",
        "=====================================================",
        f"Source ROM : {ORIG_ROM_PATH.name} ({len(orig_swapped)} bytes, sha1={orig_sha1})",
        f"Built ROM  : {out_bin.name} ({len(built_swapped)} bytes, sha1={_sha1(built_swapped)})",
        f"IPS Patch  : {out_ips.name} ({out_ips.stat().st_size} bytes, sha1={_sha1(out_ips.read_bytes())})",
        "IPS Check  : PASS (apply_ips(orig, ips) == built ROM byte-for-byte)",
        f"Expansion  : {len(alloc.allocations)} blocks allocated in 0x{len(orig_swapped):06X}..0x{EXPANDED_ROM_SIZE:06X}",
        f"Fixed/Ptrs : {len(alloc.fixed_patches)} verified non-overlapping patches",
        "",
        "Per-Target Summary:",
    ]
    total_alloc = 0
    for name, s in stats.items():
        moc, mc = s["map_comp"]  # type: ignore[misc]
        goc, gc = s["gfx_comp"]  # type: ignore[misc]
        moff = s["map_off"]
        goff = s["gfx_off"]
        total_alloc += mc + gc
        lines.append(
            f"  - {name:20s}: nt={s['nt']:3d} | tiles={s['tiles_used']:2d}/{s['free_avail']:3d} free | "
            f"map@0x{moff:06X} ({moc}->{mc}B) | gfx@0x{goff:06X} ({goc}->{gc}B)"
        )

    lines.extend(
        [
            "",
            f"Total Expansion Bytes Used: {total_alloc} / {EXPANDED_ROM_SIZE - len(orig_swapped)} bytes",
            "",
            "Expanded ROM Allocations:",
        ]
    )
    for start, end, label in sorted(alloc.allocations):
        lines.append(f"  0x{start:06X}..0x{end:06X} ({end - start:5d} B)  {label}")

    out_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    build_rom()
