"""Decompressor and encoders matching Boom Zoo's $002B22 ($D222-family) routines."""

import struct
from typing import Optional, Tuple

MAX_DECOMP_SIZE = 0x9480  # WRAM $FC0800..$FC9C80 scratch buffer (38,016 bytes)

# Extracted directly from Boom Zoo (Taiwan).bin (unswapped BE):
DEFAULT_HUFF_OFFSET = 0x002F9C  # 164 bytes ending at $003040 (a4 walks backward)
DEFAULT_DIST_OFFSET = 0x002E2A  # 256 bytes ending at $002F2A

# $002D1A table: sentinel bit positions -> reads (16 - b) stream bits after prefix byte
_SENTINEL_BITS = (15, 15, 14, 14, 14, 13, 13, 13, 13, 12, 12, 12, 11, 11, 11, 10)


def d2b22_header(buf: bytes, offset: int) -> Tuple[int, int]:
    """Emulate header read at $002B3A: return (mode, size)."""
    if offset + 4 > len(buf):
        raise ValueError(f"Offset 0x{offset:06X} out of range")
    mode = buf[offset]
    flag = buf[offset + 1]
    if mode < 0xF0 or flag != 0x00:
        raise ValueError(
            f"Invalid $002B22 header at 0x{offset:06X}: mode=0x{mode:02X} flag=0x{flag:02X}"
        )
    size = struct.unpack_from(">H", buf, offset + 2)[0]
    return mode, size


def decompress_d222(
    rom: bytes,
    offset: int,
    huff_offset: int = DEFAULT_HUFF_OFFSET,
    dist_offset: int = DEFAULT_DIST_OFFSET,
) -> Tuple[bytes, int]:
    """Exact Python implementation of Boom Zoo $002B22 (modes 0xF0 raw, 0xF1 RLE, 0xF3/0xF4 LZ+Huffman).

    Returns (decompressed_bytes, end_offset_in_rom).
    """
    mode, out_len = d2b22_header(rom, offset)
    pos = offset + 4
    if out_len == 0:
        return b"", pos

    if mode not in (0xF1, 0xF3, 0xF4):
        end = pos + out_len
        return bytes(rom[pos:end]), end

    if mode == 0xF1:
        out = bytearray()
        rem = out_len
        p = pos
        while rem > 0:
            ctrl = rom[p]
            p += 1
            if ctrl <= 0xBF:
                out.append(ctrl)
                rem -= 1
            else:
                cnt = (ctrl & 0x3F) or 1
                val = rom[p]
                p += 1
                out.extend((val,) * cnt)
                rem -= cnt
                if rem < 0:
                    raise ValueError(f"0xF1 RLE overshoot at 0x{offset:06X}: rem={rem}")
        return bytes(out), p

    if mode == 0xF3:
        huff_raw = rom[pos : pos + 164]
        p = pos + 164
    else:
        huff_raw = rom[huff_offset : huff_offset + 164]
        p = pos

    dist_tbl = rom[dist_offset : dist_offset + 256]

    buckets = [-1] * 16
    chain = [0] * 328
    word_idx = 327
    for b in reversed(huff_raw):
        lo = b & 0x0F
        hi = (b >> 4) & 0x0F
        chain[word_idx] = buckets[lo]
        buckets[lo] = word_idx
        word_idx -= 1
        chain[word_idx] = buckets[hi]
        buckets[hi] = word_idx
        word_idx -= 1

    tree = []
    next_node_word = 1
    rem_slots = 2
    for bitlen_idx in range(16):
        cur = buckets[bitlen_idx]
        while cur >= 0:
            tree.append(cur - 0x200)
            rem_slots -= 1
            cur = chain[cur]
        for _ in range(rem_slots):
            tree.append(next_node_word)
            next_node_word += 1
        rem_slots <<= 1
        if len(tree) >= 0x51C // 2:
            break

    out = bytearray()
    bit_buf = 0
    bit_cnt = 0

    def read_bit() -> int:
        nonlocal p, bit_buf, bit_cnt
        if bit_cnt == 0:
            bit_buf = rom[p]
            p += 1
            bit_cnt = 8
        b = (bit_buf >> 7) & 1
        bit_buf = (bit_buf << 1) & 0xFF
        bit_cnt -= 1
        return b

    while True:
        node = 0
        while True:
            val = tree[node * 2 + read_bit()]
            if val < 0:
                sym = val + 0x200
                break
            node = val

        if sym < 256:
            out.append(sym)
        elif sym < 266:
            sub = sym - 256
            if sub == 0:
                break
            elif sub == 1:
                out.append(out[-1])
            elif sub == 2:
                out.append(out[-2])
            elif sub == 3:
                out.append(out[-4])
            elif sub == 4:
                out.append(out[-29])
            elif sub == 5:
                out.append(out[-2])
                out.append(out[-2])
            elif sub == 6:
                for _ in range(4):
                    out.append(out[-4])
            elif sub == 7:
                for _ in range(8):
                    out.append(out[-8])
            elif sub == 8:
                out.append(out[-2])
                out.append((out[-2] - 1) & 0xFF)
            elif sub == 9:
                out.append(out[-2])
                out.append((out[-2] + 1) & 0xFF)
        else:
            match_len = sym - 266 + 3
            prefix = rom[p]
            p += 1
            hi_nib = prefix >> 4
            n_extra = 16 - _SENTINEL_BITS[hi_nib]
            val16 = prefix
            for _ in range(n_extra):
                val16 = (val16 << 1) | read_bit()
            dist = ((dist_tbl[prefix] << 6) | (val16 & 0x3F)) + 1
            for _ in range(match_len):
                out.append(out[-dist])

        if len(out) >= out_len:
            break

    return bytes(out[:out_len]), p


def encode_d222_raw(data: bytes) -> bytes:
    """Encode uncompressed block with 0xF0 header matching $002B22 raw fallback."""
    if len(data) == 0 or len(data) > MAX_DECOMP_SIZE or (len(data) & 1):
        raise ValueError(f"Invalid $002B22 payload length {len(data)}")
    return bytes([0xF0, 0x00]) + struct.pack(">H", len(data)) + data


def encode_d222_rle(data: bytes) -> bytes:
    """Encode using $002B22 mode 0xF1 RLE."""
    n = len(data)
    if n == 0 or n > MAX_DECOMP_SIZE or (n & 1):
        raise ValueError(f"Invalid $002B22 payload length {n}")
    out = bytearray([0xF1, 0x00])
    out.extend(struct.pack(">H", n))
    i = 0
    while i < n:
        v = data[i]
        run = 1
        while i + run < n and run < 63 and data[i + run] == v:
            run += 1
        if run >= 3 or (run >= 2 and v >= 0xC0):
            out.append(0xC0 | run)
            out.append(v)
            i += run
        elif v >= 0xC0:
            out.append(0xC1)
            out.append(v)
            i += 1
        else:
            out.append(v)
            i += 1
    return bytes(out)


def encode_d222_best(data: bytes, verify_rom: Optional[bytes] = None) -> bytes:
    """Return shorter of RLE (0xF1) and Raw (0xF0), self-verified by round-trip decode."""
    rle = encode_d222_rle(data)
    raw = encode_d222_raw(data)
    best = rle if len(rle) <= len(raw) else raw
    dec, end = decompress_d222(best, 0)
    if dec != data or end != len(best):
        raise AssertionError("Self-check failed in encode_d222_best")
    return best
