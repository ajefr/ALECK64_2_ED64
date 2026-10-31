#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aleck2ed64.py - Converts Aleck 64 ROM dumps (MAME format) into .z64 images
that an EverDrive 64 can load, to run them on an Aleck 64 motherboard fitted
with an N64 cartridge slot adapter.

Written by Claude (Anthropic's AI model), at the request of aje_fr.

For each game, the script:
  1. finds the ROM chips (in MAME .zip sets, folders or loose files),
     identifying them by CRC32 (file names do not matter);
  2. puts each chip back into big-endian byte order (.z64): MAME loads them
     with ROM_LOAD16_WORD_SWAP, so the dumps are byte-swapped (.v64);
  3. concatenates the chips in cartridge bus order (u3 at 0x0000000,
     u4 at 0x1000000 for the Aruze games);
  4. checks the N64 header, detects the CIC (IPL3) and verifies the header
     checksum with the CIC-NUS-5101 algorithm (seed 0xAC);
  5. bypasses the checksum check of the 5101 IPL3, which the EverDrive does
     not know about (see --mode);
  6. writes <game>.z64.

Python 3.7+ only, no dependencies.

Sources: MAME driver src/mame/nintendo/aleck64.cpp (chips, CRCs, byte order,
0x67C patch) and the ipl3checksum library (CIC 5101 algorithm and seed).
"""

import argparse
import hashlib
import os
import struct
import sys
import zipfile
import zlib

# ---------------------------------------------------------------------------
# Game table, taken from the MAME aleck64.cpp driver
# (MAME file name, cartridge bus offset, size, CRC32, SHA1)
# ---------------------------------------------------------------------------
GAMES = {
    "11beat": {
        "title": "Eleven Beat (Hudson Soft, 1998)",
        "chips": [("nus-zhaj.u3", 0x0000000, 0x0800000, 0x02FAA8A7, "824911452639cedf6a8186c05cd046e61fc98896")],
    },
    "mtetrisc": {
        "title": "Magical Tetris Challenge (Capcom, 1998) - E90 board",
        "chips": [("nus-zcaj.u4", 0x0000000, 0x1000000, 0xC9DE64DB, "59932c70b43ff8e9264c670f37b3abbe939b7f95")],
        "extra": [("tet-01m.u5", 0xF78F859B), ("at24c01.u34", None)],
        "unsupported": "E90 motherboard game (not a cartridge): it needs the E90 graphics chip "
                       "and the tet-01m.u5 ROM soldered on that board. On an E92 board the "
                       "playfield will not be drawn.",
    },
    "starsldr": {
        "title": "Star Soldier: Vanishing Earth (Hudson / Seta, 1998)",
        "chips": [("nus-zhbj-0.u3", 0x0000000, 0x0C00000, 0xA4EDAC93, "3794606c008fb69f5d16dcccece94d03da23bf8a")],
    },
    "srmvs": {
        "title": "Super Real Mahjong VS Rev A (Seta, 1999)",
        "chips": [("nus-zsej-1.u2", 0x0000000, 0x2000000, 0xDD7DD81F, "ff020fa957a11bf0f18819d16a010f51b4a4cda4")],
    },
    "srmvsa": {
        "title": "Super Real Mahjong VS (Seta, 1999)",
        "chips": [("nus-zsej-0.u2", 0x0000000, 0x2000000, 0x44F40102, "a78de955f2fcd99dda14e782984368b320eb5415")],
    },
    "vivdolls": {
        "title": "Vivid Dolls (Visco, 1998)",
        "chips": [("nus-zsaj-0.u3", 0x0000000, 0x0800000, 0xF3220E29, "06d8b808cc19378b046803f4dc75c7d791b7767f")],
    },
    "mayjin3": {
        "title": "Mayjinsen 3 (Seta / Able, 2000)",
        "chips": [("nus-zscj-0.u3", 0x0000000, 0x0800000, 0x52A37340, "b5834bfde5b8a7e20415b2593abd76ec95ab27c7")],
    },
    "twrshaft": {
        "title": "Tower & Shaft (Aruze, 2003)",
        "chips": [("ua3012-all02.u3", 0x0000000, 0x1000000, 0x904A91A7, "7dfa3447d2c489c0448c4004dc12d3037c05a0f3")],
        "extra": [("nus-zsij-0.u1", 0x2389576F)],
        "aruze": True,
    },
    "hipai": {
        "title": "Hi Pai Paradise (Aruze / Seta, 2003)",
        "chips": [("ua2011-all02.u3", 0x0000000, 0x1000000, 0xEB4B96D0, "e909ea5b71b81087da07821c4f57244576363678"),
                  ("ua2011-alh02.u4", 0x1000000, 0x1000000, 0xB8E35DDF, "7c3e59f6520dc3f0aa592e682fa82e30ffd1f4d0")],
        "extra": [("nus-nsij-0.u1", 0x94CF9F8D)],
        "aruze": True,
    },
    "hipai2": {
        "title": "Hi Pai Paradise 2 (Aruze / Seta / Paon, 2004)",
        "chips": [("ua3029-all01.u3", 0x0000000, 0x1000000, 0x88B83E93, "279a006436069232383b2065e7416d8ccc76e3ca"),
                  ("ua3029-alh01.u4", 0x1000000, 0x1000000, 0x4F79FA94, "a6d2d805f96f0ad7294ebf41b13573320154b2a4")],
        "extra": [("nus-zsij-0.u1", 0x2389576F)],
        "aruze": True,
    },
    "kurufev": {
        "title": "Kurukuru Fever (Aruze / Takumi, 2003)",
        "chips": [("ua3088-all01.u3", 0x0000000, 0x1000000, 0x00DB4DBC, "824fdce01fffdfcbcc9b1fbda4ab389a10b2b418"),
                  ("ua3088-alh04.u4", 0x1000000, 0x1000000, 0xC96BC7C0, "2b6ca1a769dee74e112c2b287dacd0bf46dda091")],
        "extra": [("nus-zsij-0.u1", 0x2389576F)],
        "aruze": True,
    },
    "doncdoon": {
        "title": "Hanabi de Doon! - Don-chan Puzzle (Aruze, 2003)",
        "chips": [("ua3003-all01.u3", 0x0000000, 0x1000000, 0xF362FA82, "4f41ee23edc18110be1218ba333d1c58376ab175"),
                  ("ua3003-alh01.u4", 0x1000000, 0x1000000, 0x47C56387, "c8cc6c0a456b593aef711d0a75b2342ba2f8203f")],
        "extra": [("nus-zsij-0.u1", 0x547D8122)],
        "aruze": True,
    },
}

# CRC32 -> (game, chip index)
CRC_INDEX = {}
for _set, _g in GAMES.items():
    for _i, _c in enumerate(_g["chips"]):
        CRC_INDEX.setdefault(_c[3], []).append((_set, _i))

# IPL3 MD5s (0x40-0xFFF, z64 order), from ipl3checksum
IPL3_MD5 = {
    "900b4a5b68edb71f4c7ed52acd814fc5": "6101",
    "e24dd796b2fa16511521139d28c8356b": "6102/7101",
    "955894c2e40a698bf98a67b78a4e28fa": "7102",
    "319038097346e12c26c3c21b56f86f23": "6103/7103",
    "ff22a296e55d34ab0a077dc2ba5f5796": "6105/7105",
    "6460387749ac0bd925aa5430bc7864fe": "6106/7106",
    "711f8c3ac54fc70a42626bf6c171443d": "5101",
}

PATCH_OFFSET = 0x67C        # word NOPed by MAME (init_aleck64)
ED64_SAVE_EEPROM4K = 0x10   # byte 0x3F of the ED64 advanced header: high nibble = 1


# ---------------------------------------------------------------------------
# Byte order
# ---------------------------------------------------------------------------
def byte_order(head4):
    if head4 == b"\x80\x37\x12\x40":
        return "z64"
    if head4 == b"\x37\x80\x40\x12":
        return "v64"
    if head4 == b"\x40\x12\x37\x80":
        return "n64"
    return None


def to_z64(data, order):
    if order == "z64":
        return bytes(data)
    b = bytearray(data)
    if order == "v64":
        b[0::2], b[1::2] = data[1::2], data[0::2]
    elif order == "n64":
        b[0::4], b[1::4], b[2::4], b[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
    return bytes(b)


# ---------------------------------------------------------------------------
# Header checksum (CIC x103 / 5101 algorithm, see ipl3checksum)
# ---------------------------------------------------------------------------
def checksum_5101(rom, seed=0xAC):
    M = 0xFFFFFFFF
    magic = 0x6C078965
    v0 = (seed * magic + 1) & M
    a3 = t2 = t3 = s0 = a2 = t4 = v0
    entry = (struct.unpack_from(">I", rom, 8)[0] - 0x100000) & M
    length = 0x3FE000 if entry == 0x80000400 else 0x100000
    if len(rom) < 0x1000 + length:
        raise ValueError("ROM too small to compute the checksum")
    words = struct.unpack_from(">%dI" % (length // 4), rom, 0x1000)
    for w in words:
        a1 = (a3 + w) & M
        if a1 < a3:
            t2 = (t2 + 1) & M
        a3 = a1
        r = w & 0x1F
        a0 = ((w << r) | (w >> (32 - r))) & M if r else w
        t3 ^= w
        s0 = (s0 + a0) & M
        if a2 < w:
            a2 ^= a3 ^ w
        else:
            a2 ^= a0
        t4 = (t4 + (w ^ s0)) & M
    crc1 = ((a3 ^ t2) + t3) & M
    crc2 = ((s0 ^ a2) + t4) & M
    return crc1, crc2


def is_branch(word):
    op = word >> 26
    return op in (0x01, 0x04, 0x05, 0x06, 0x07, 0x14, 0x15, 0x16, 0x17)


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------
def iter_inputs(paths):
    """Yields (group, name, data) tuples. The group is the zip or folder."""
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    yield from iter_inputs([os.path.join(root, f)])
        elif zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        yield p, os.path.basename(info.filename), z.read(info)
        elif os.path.isfile(p):
            yield os.path.dirname(os.path.abspath(p)), os.path.basename(p), open(p, "rb").read()
        else:
            print("  ! not found: %s" % p)


# ---------------------------------------------------------------------------
# Converting one game
# ---------------------------------------------------------------------------
def build_rom(setname, chips_found, args):
    g = GAMES[setname]
    print("\n== %s: %s" % (setname, g["title"]))
    if g.get("unsupported"):
        print("  ! NOT SUPPORTED: " + g["unsupported"])
        if not args.force:
            print("  -> skipped (use --force to convert it anyway)")
            return False

    total = max(off + size for (_n, off, size, _c, _s) in g["chips"])
    rom = bytearray(total)
    order = None
    for i, (name, off, size, crc, sha1) in enumerate(g["chips"]):
        fname, data = chips_found[i]
        if hashlib.sha1(data).hexdigest() != sha1:
            print("  ! SHA1 differs from MAME for %s (same CRC): suspicious dump" % fname)
        if i == 0:
            order = byte_order(data[:4])
            if order is None:
                print("  ! no N64 header found in %s, assuming v64 order (as MAME does)" % fname)
                order = "v64"
        rom[off:off + size] = to_z64(data, order)
        print("  + %-18s -> 0x%07X (%d MB, %s order)" % (fname, off, size >> 20, order))
    for name, _crc in g.get("extra", []):
        print("  . %s not used (MAME does not map it on the cartridge bus)" % name)
    return finish_rom(setname, rom, args)


def finish_rom(setname, rom, args):
    if bytes(rom[:4]) != b"\x80\x37\x12\x40":
        print("  ! header does not start with 80 37 12 40: conversion aborted")
        return False

    title = bytes(rom[0x20:0x34]).decode("ascii", "replace").strip()
    code = bytes(rom[0x3B:0x3F]).decode("ascii", "replace")
    print("  Internal title: %r, game code: %r" % (title, code))

    md5 = hashlib.md5(bytes(rom[0x40:0x1000])).hexdigest()
    cic = IPL3_MD5.get(md5, "unknown (%s)" % md5)
    print("  CIC (IPL3)    : %s" % cic)

    hdr = struct.unpack_from(">II", rom, 0x10)
    if cic == "5101":
        calc = checksum_5101(rom, 0xAC)
        ok = calc == hdr
        print("  Checksum      : header %08X %08X, computed %08X %08X -> %s"
              % (hdr + calc + ("OK, good dump" if ok else "MISMATCH, bad dump?",)))

    mode = args.mode
    if mode == "patch":
        w = struct.unpack_from(">I", rom, PATCH_OFFSET)[0]
        if w == 0:
            print("  Patch 0x67C   : already applied")
        elif cic == "5101" and is_branch(w) or args.force:
            struct.pack_into(">I", rom, PATCH_OFFSET, 0)
            print("  Patch 0x67C   : branch %08X replaced by NOP" % w)
        else:
            print("  ! Patch 0x67C : unexpected word %08X, patch NOT applied (--force to force it)" % w)
    elif mode == "recrc":
        if cic != "5101":
            print("  ! --mode recrc only makes sense for a 5101 IPL3: header left unchanged")
        else:
            c1, c2 = checksum_5101(rom, args.seed)
            struct.pack_into(">II", rom, 0x10, c1, c2)
            print("  New CRC       : %08X %08X (seed 0x%02X)" % (c1, c2, args.seed))
    else:
        print("  IPL3 left untouched (--mode none)")

    if args.ed64_header:
        rom[0x3C:0x3E] = b"ED"
        rom[0x3F] = ED64_SAVE_EEPROM4K
        print("  ED64 header   : EEPROM 4K save declared (bytes 0x3C-0x3F)")

    if args.pad and len(rom) & (len(rom) - 1):
        size = 1 << (len(rom) - 1).bit_length()
        rom += b"\xFF" * (size - len(rom))
        print("  Padded to %d MB" % (size >> 20))

    os.makedirs(args.output, exist_ok=True)
    out = os.path.join(args.output, setname + ".z64")
    with open(out, "wb") as f:
        f.write(rom)
    print("  => %s (%d MB)" % (out, len(rom) >> 20))
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Converts Aleck 64 ROMs (MAME format) into .z64 files for the EverDrive 64.")
    ap.add_argument("inputs", nargs="+",
                    help="MAME .zip sets, folders, or chip files (.u2/.u3/.u4)")
    ap.add_argument("-o", "--output", default="ed64_out", help="output folder (default: ed64_out)")
    ap.add_argument("--mode", choices=("patch", "recrc", "none"), default="patch",
                    help="patch: NOP the checksum check at 0x67C, as MAME does (default); "
                         "recrc: rewrite the header CRC for the --seed seed without touching the code; "
                         "none: leave the ROM untouched")
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x3F,
                    help="CIC seed passed by the EverDrive, for --mode recrc (default 0x3F = 6102)")
    ap.add_argument("--ed64-header", action="store_true",
                    help="write the ED64 advanced header declaring an EEPROM 4K save "
                         "(overwrites the cartridge ID at 0x3C-0x3D and the version byte at 0x3F)")
    ap.add_argument("--pad", action="store_true",
                    help="pad the ROM to the next power of 2 (e.g. starsldr 12 -> 16 MB)")
    ap.add_argument("--force", action="store_true",
                    help="also convert unsupported games and force the patch")
    args = ap.parse_args()

    found = {}       # setname -> {index: (fname, data)}
    unknown = []
    for group, name, data in iter_inputs(args.inputs):
        crc = zlib.crc32(data) & 0xFFFFFFFF
        if crc in CRC_INDEX:
            for setname, idx in CRC_INDEX[crc]:
                found.setdefault(setname, {})[idx] = (name, data)
        else:
            known_extra = any(crc == e[1] for g in GAMES.values() for e in g.get("extra", []))
            if not known_extra and len(data) >= 0x100000 and name.lower() != "pifdata.bin":
                unknown.append((group, name))

    ok = 0
    for setname in GAMES:
        if setname not in found:
            continue
        got = found[setname]
        need = len(GAMES[setname]["chips"])
        if len(got) < need:
            missing = [GAMES[setname]["chips"][i][0] for i in range(need) if i not in got]
            print("\n== %s: missing chip(s): %s" % (setname, ", ".join(missing)))
            continue
        if build_rom(setname, got, args):
            ok += 1

    for group, name in unknown:
        print("\n? %s (%s): unknown CRC, not an Aleck 64 chip listed by MAME" % (name, group))

    print("\n%d ROM(s) written to %s" % (ok, args.output))
    if ok:
        print("Reminder: in the ED64 menu, set the save type to EEPROM 4K for each game "
              "(unless --ed64-header was used).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
