"""ROM I/O, byteswapping, IPS patching, expansion space allocator, and PPU tile/tilemap codecs for Boom Zoo."""

from pathlib import Path
import struct
from typing import Dict, List, Optional, Sequence, Tuple

ORIG_ROM_PATH = Path(__file__).resolve().parent.parent / "Boom Zoo (Taiwan).bin"   # your own dump, next to README
ORIG_ROM_SIZE = 0x080000
EXPANDED_ROM_SIZE = 0x100000

TileGrid = List[List[int]]
TileKey = Tuple[Tuple[int, ...], ...]


def byteswap_16(data: bytes) -> bytes:
    """Swap adjacent bytes in 16-bit words (file LE <-> M68K BE)."""
    if len(data) & 1:
        raise ValueError(f"Odd ROM length {len(data)}")
    out = bytearray(len(data))
    out[0::2] = data[1::2]
    out[1::2] = data[0::2]
    return bytes(out)


def load_orig_rom_unswapped(
    rom_path: Path = ORIG_ROM_PATH,
    expand_1mb: bool = True,
    pad_byte: int = 0xFF,
) -> bytearray:
    """Read the original byteswapped ROM into big-endian M68K order, optionally expanded to 1 MB."""
    raw = rom_path.read_bytes()
    if len(raw) != ORIG_ROM_SIZE:
        raise ValueError(f"Expected {ORIG_ROM_SIZE} bytes at {rom_path}, got {len(raw)}")
    rom = bytearray(byteswap_16(raw))
    if expand_1mb and len(rom) < EXPANDED_ROM_SIZE:
        rom.extend(bytes([pad_byte & 0xFF]) * (EXPANDED_ROM_SIZE - len(rom)))
    return rom


def save_rom_swapped(rom_be: bytes, out_path: Path) -> None:
    """Byteswap M68K big-endian ROM back to emulator little-endian word order and save."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(byteswap_16(rom_be))


def write_ips(orig_swapped: bytes, mod_swapped: bytes, ips_path: Path) -> None:
    """Write a standard IPS patch transforming orig_swapped into mod_swapped (supports size growth)."""
    orig_len = len(orig_swapped)
    mod_len = len(mod_swapped)
    if mod_len > 0xFFFFFF:
        raise ValueError(f"ROM size {mod_len:#x} exceeds 24-bit IPS limit")

    out = bytearray(b"PATCH")
    i = 0
    while i < mod_len:
        b_mod = mod_swapped[i]
        b_orig = orig_swapped[i] if i < orig_len else None
        if b_orig == b_mod:
            i += 1
            continue
        start = i
        chunk = bytearray()
        same_run = 0
        while i < mod_len and len(chunk) < 0xFFFF:
            cur_mod = mod_swapped[i]
            cur_orig = orig_swapped[i] if i < orig_len else None
            chunk.append(cur_mod)
            if cur_orig == cur_mod:
                same_run += 1
                if same_run >= 8:
                    # Trim trailing unchanged tail when original ROM already has matching bytes
                    del chunk[-same_run:]
                    i -= same_run - 1
                    break
            else:
                same_run = 0
            i += 1
        # Avoid 0x454F46 ("EOF") record offset ambiguity in standard IPS parsers
        if start == 0x454F46 and start > 0:
            start -= 1
            chunk.insert(0, mod_swapped[start])
        out.extend(start.to_bytes(3, "big"))
        out.extend(len(chunk).to_bytes(2, "big"))
        out.extend(chunk)
        if i <= start:
            i = start + len(chunk)
    out.extend(b"EOF")
    ips_path.parent.mkdir(parents=True, exist_ok=True)
    ips_path.write_bytes(out)


def apply_ips(orig_swapped: bytes, ips_path: Path) -> bytes:
    """Apply an IPS patch to orig_swapped and return the patched image."""
    patch = ips_path.read_bytes()
    if not patch.startswith(b"PATCH"):
        raise ValueError(f"Invalid IPS header in {ips_path}")
    out = bytearray(orig_swapped)
    pos = 5
    while pos + 3 <= len(patch):
        if patch[pos : pos + 3] == b"EOF":
            break
        off = int.from_bytes(patch[pos : pos + 3], "big")
        pos += 3
        size = struct.unpack_from(">H", patch, pos)[0]
        pos += 2
        if size == 0:
            rle_len = struct.unpack_from(">H", patch, pos)[0]
            val = patch[pos + 2]
            pos += 3
            need = off + rle_len
            if need > len(out):
                out.extend(b"\x00" * (need - len(out)))
            out[off:need] = bytes([val]) * rle_len
        else:
            data = patch[pos : pos + size]
            pos += size
            need = off + size
            if need > len(out):
                out.extend(b"\x00" * (need - len(out)))
            out[off:need] = data
    return bytes(out)


class SpaceAllocator:
    """Tracks free ROM regions and verifies non-overlapping writes."""

    def __init__(self, regions: Optional[Sequence[Tuple[int, int]]] = None) -> None:
        base = list(regions) if regions is not None else [(ORIG_ROM_SIZE, EXPANDED_ROM_SIZE)]
        self.free_regions: List[List[int]] = [[s, e] for s, e in sorted(base) if e > s]
        self.allocations: List[Tuple[int, int, str]] = []
        self.fixed_patches: List[Tuple[int, int, str]] = []

    def allocate(self, size: int, label: str, align: int = 2) -> int:
        """Allocate `size` aligned bytes from free regions and record the range."""
        if size <= 0:
            raise ValueError(f"Allocation size must be positive for {label}: {size}")
        for idx, reg in enumerate(self.free_regions):
            s, e = reg
            aligned = (s + (align - 1)) & ~(align - 1)
            if aligned + size <= e:
                end = aligned + size
                if aligned > s:
                    if end < e:
                        self.free_regions[idx] = [s, aligned]
                        self.free_regions.insert(idx + 1, [end, e])
                    else:
                        reg[1] = aligned
                elif end < e:
                    reg[0] = end
                else:
                    self.free_regions.pop(idx)
                self.allocations.append((aligned, end, label))
                return aligned
        raise MemoryError(f"Out of expanded ROM space allocating {size} bytes for {label}")

    def record_patch(self, start: int, end: int, label: str) -> None:
        """Record an in-place ROM patch range [start, end) for overlap validation and reporting."""
        if end <= start:
            raise ValueError(f"Invalid patch range [{start:#x}, {end:#x}) for {label}")
        self.fixed_patches.append((start, end, label))

    def verify_non_overlapping(self) -> None:
        """Ensure no two recorded allocations or fixed patches overlap."""
        items = sorted(self.allocations + self.fixed_patches, key=lambda x: (x[0], x[1]))
        for (s1, e1, l1), (s2, e2, l2) in zip(items, items[1:]):
            if s2 < e1:
                raise AssertionError(
                    f"Overlapping ROM writes: {l1} [0x{s1:06X}..0x{e1:06X}) "
                    f"vs {l2} [0x{s2:06X}..0x{e2:06X})"
                )


def decode_tile_4bpp(tile32: bytes) -> TileGrid:
    """Decode one 32-byte 4bpp 8x8 tile into an 8x8 list of palette indices [0..15]."""
    if len(tile32) != 32:
        raise ValueError(f"Expected 32 bytes for 4bpp tile, got {len(tile32)}")
    rows: TileGrid = []
    for y in range(8):
        row: List[int] = []
        base = y * 4
        for x in range(4):
            b = tile32[base + x]
            row.append((b >> 4) & 0xF)
            row.append(b & 0xF)
        rows.append(row)
    return rows


def encode_tile_4bpp(grid: Sequence[Sequence[int]]) -> bytes:
    """Encode an 8x8 grid of nibble indices [0..15] into 32 bytes of 4bpp tile data."""
    if len(grid) != 8 or any(len(r) != 8 for r in grid):
        raise ValueError("Tile grid must be 8x8")
    out = bytearray(32)
    for y in range(8):
        row = grid[y]
        base = y * 4
        for x in range(4):
            hi = row[x * 2] & 0xF
            lo = row[x * 2 + 1] & 0xF
            out[base + x] = (hi << 4) | lo
    return bytes(out)


def flip_tile_grid(grid: Sequence[Sequence[int]], hflip: bool, vflip: bool) -> TileKey:
    """Return an immutable 8x8 tuple with optional horizontal and vertical flip."""
    ys = range(7, -1, -1) if vflip else range(8)
    xs = range(7, -1, -1) if hflip else range(8)
    return tuple(tuple(grid[y][x] & 0xF for x in xs) for y in ys)


def tilemap_word(
    tile_idx: int,
    pal: int,
    hflip: bool = False,
    vflip: bool = False,
    prio: bool = False,
) -> int:
    """Build a Super A'Can 16-bit tilemap word (0x0400=vflip, 0x0800=hflip)."""
    return (
        ((1 if prio else 0) << 15)
        | ((pal & 0xF) << 12)
        | ((1 if hflip else 0) << 11)
        | ((1 if vflip else 0) << 10)
        | (tile_idx & 0x3FF)
    )


def unpack_gfx_block(dec: bytes) -> List[TileGrid]:
    """Unpack a decompressed Boom Zoo gfx block (u16 word_count = nt*16 + 32*nt bytes)."""
    if len(dec) < 2:
        raise ValueError("Empty gfx block")
    word_count = struct.unpack_from(">H", dec, 0)[0]
    expected_bytes = 2 + word_count * 2
    if len(dec) < expected_bytes or (word_count % 16) != 0:
        raise ValueError(
            f"Unexpected gfx block header word_count={word_count} for len={len(dec)}"
        )
    nt = word_count // 16
    return [decode_tile_4bpp(dec[2 + i * 32 : 2 + (i + 1) * 32]) for i in range(nt)]


def pack_gfx_block(tiles: Sequence[Sequence[Sequence[int]]]) -> bytes:
    """Pack tiles into a Boom Zoo gfx block with u16 BE word-count header (`nt * 16`)."""
    nt = len(tiles)
    out = bytearray(2 + nt * 32)
    struct.pack_into(">H", out, 0, nt * 16)
    for i, grid in enumerate(tiles):
        out[2 + i * 32 : 2 + (i + 1) * 32] = encode_tile_4bpp(grid)
    return bytes(out)


def unpack_spr_tilemap(dec: bytes) -> List[int]:
    """Unpack a decompressed sprite tilemap block (`u16 nwords` header + words)."""
    nwords = struct.unpack_from(">H", dec, 0)[0]
    if len(dec) < 2 + nwords * 2:
        raise ValueError(f"Sprite tilemap truncated: nwords={nwords}, len={len(dec)}")
    return list(struct.unpack_from(f">{nwords}H", dec, 2))


def pack_spr_tilemap(words: Sequence[int]) -> bytes:
    """Pack a sprite tilemap list into `u16 nwords` + `u16 BE` words."""
    n = len(words)
    return struct.pack(f">H{n}H", n, *(w & 0xFFFF for w in words))


def unpack_bg_tilemap(dec: bytes) -> List[int]:
    """Unpack a decompressed BG tilemap (raw 960 u16 BE words = 32x30, no header)."""
    if len(dec) != 1920:
        raise ValueError(f"Expected 1920-byte BG tilemap (32x30), got {len(dec)}")
    return list(struct.unpack_from(">960H", dec, 0))


def pack_bg_tilemap(words: Sequence[int]) -> bytes:
    """Pack 960 u16 BE words into a 1920-byte BG tilemap."""
    if len(words) != 960:
        raise ValueError(f"Expected 960 BG tilemap words, got {len(words)}")
    return struct.pack(">960H", *(w & 0xFFFF for w in words))
