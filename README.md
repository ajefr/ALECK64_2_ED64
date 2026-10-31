# ALECK64_2_ED64

> **This project was written by Claude, Anthropic's AI model,** at the request of aje_fr. The research, the code and this documentation were all produced by Claude. No converted game had been tried on real hardware when the project was published.

`aleck2ed64.py` converts Aleck 64 arcade ROM dumps in MAME format into `.z64` images that an **EverDrive 64** can load.

The intended setup is a real **Aleck 64 motherboard** (Seta E92) with an N64 cartridge slot adapter and the EverDrive 64 plugged into it. The games still need the Aleck board hardware: the arcade inputs, the DIP switches and the extra SDRAM. **They will not run on a stock N64 console.**

No ROMs are included. You need your own dumps.

## Usage

The script needs Python 3.7 or later and has no dependencies.

```
python3 aleck2ed64.py path/to/mame_roms -o ed64_out
python3 aleck2ed64.py 11beat.zip hipai.zip -o ed64_out
python3 aleck2ed64.py nus-zhaj.u3 -o ed64_out
```

It accepts MAME `.zip` sets, whole folders or loose chip files. Each chip is identified by its CRC32, so file names do not matter. After converting:

1. Copy the `.z64` files from the output folder to the EverDrive SD card.
2. In the ED64 menu, set the save type to **EEPROM 4K** for each game. The Aleck cartridges carry a BK4D-NUS / BU9850, the same 4 Kbit EEPROM used in N64 cartridges.

### Options

| Option | Effect |
|---|---|
| `--mode patch` (default) | Disables the IPL3 checksum check at 0x67C by replacing it with a NOP. MAME applies the same patch to every Aleck game. |
| `--mode recrc --seed 0x3F` | Fallback: leaves the code alone and rewrites the header CRC for the 6102 seed. |
| `--mode none` | Leaves the ROM untouched. Only useful if your ED64 OS supports the 5101 CIC. |
| `--ed64-header` | Declares EEPROM 4K in the ED64 advanced header (bytes 0x3C-0x3F) so nothing has to be set in the menu. This overwrites the original cartridge ID. |
| `--pad` | Pads the ROM to the next power of 2 (starsldr goes from 12 MB to 16 MB). |
| `--force` | Also converts mtetrisc, and forces the patch when the expected instruction is not found. |

## What the conversion does

- **Byte order**: MAME loads every one of these chips with `ROM_LOAD16_WORD_SWAP`, so the dumps are byte-swapped (.v64 order). The script detects the order from the `80 37 12 40` header and writes big-endian (.z64).
- **Assembly**: the u3 (or u2) chip goes at 0x0000000. On the Aruze games, u4 follows at 0x1000000, which gives a 32 MB ROM. The `nus-zsij-0.u1` / `nus-nsij-0.u1` chip of the Aruze cartridges is left out, because MAME does not map it on the cartridge bus and it is mostly empty.
- **Verification**: the script identifies the IPL3 by its MD5 and computes the header checksum with the CIC-NUS-5101 algorithm (seed 0xAC). If it prints "OK, good dump", both the dump and the byte order are right.
- **Why a patch is needed**: Aleck cartridges use a CIC-NUS-5101, which the EverDrive does not know about. The ED64 therefore boots the game with the 6102 seed (0x3F), the IPL3 gets a checksum mismatch and the game hangs on a black screen. The NOP at 0x67C removes that hang. MAME does the same thing in `init_aleck64`, with the same 6102 seed. The script only applies the patch when it finds the 5101 IPL3 and a branch instruction at that address.

## Per-game compatibility

**None of these games has been tested on real hardware.** The script was checked against synthetic ROMs for chip assembly, byte order, the patch and the checksum, which matches the reference [ipl3checksum](https://pypi.org/project/ipl3checksum/) library. Reports from real hardware are welcome as GitHub issues.

| MAME set | Title | Chips | .z64 size | Expected result |
|---|---|---|---|---|
| 11beat | Eleven Beat | nus-zhaj.u3 | 8 MB | Should work (standard 3D ROM PCB cartridge) |
| starsldr | Star Soldier: Vanishing Earth | nus-zhbj-0.u3 | 12 MB | Should work |
| vivdolls | Vivid Dolls | nus-zsaj-0.u3 | 8 MB | Should work |
| mayjin3 | Mayjinsen 3 | nus-zscj-0.u3 | 8 MB | Should work |
| srmvs / srmvsa | Super Real Mahjong VS | nus-zsej-1.u2 / -0.u2 | 32 MB | Should work. Needs the cabinet's mahjong panel. |
| twrshaft | Tower & Shaft | ua3012-all02.u3 | 16 MB | Uncertain: Aruze cartridge with a CPLD, see below |
| hipai | Hi Pai Paradise | ua2011-all02.u3 + alh02.u4 | 32 MB | Uncertain (Aruze), mahjong panel |
| hipai2 | Hi Pai Paradise 2 | ua3029-all01.u3 + alh01.u4 | 32 MB | Uncertain (Aruze), mahjong panel |
| kurufev | Kurukuru Fever | ua3088-all01.u3 + alh04.u4 | 32 MB | Uncertain (Aruze) |
| doncdoon | Hanabi de Doon! | ua3003-all01.u3 + alh01.u4 | 32 MB | Uncertain (Aruze) |
| mtetrisc | Magical Tetris Challenge | nus-zcaj.u4 | 16 MB | **Not supported**: skipped by default, see below |

### Special hardware

- **Aruze cartridges** (twrshaft, hipai, hipai2, kurufev, doncdoon) carry an Altera CPLD (AL01) and flash memory instead of a mask ROM. MAME runs them with a plain linear mapping and does not emulate the CPLD, which suggests the CPLD does little. If it does banking or protection on real hardware, the EverDrive cannot reproduce it. These are the first games to try.
- **mtetrisc** is not a cartridge game. It runs on the E90 motherboard and needs the E90 graphics chip and the `tet-01m.u5` ROM soldered on that board. On an E92 board with a cartridge slot, the playfield will not be drawn.
- **Size**: the 32 MB games need an ED64 that handles 32 MB or more, such as the V3 or X7.

## If you get a black screen

1. Check that the script output shows "CIC 5101", "Checksum OK" and "Patch 0x67C".
2. Try `--mode recrc`.
3. Update the ED64 OS and check that the save type is set to EEPROM 4K.

## Sources

- MAME driver [`aleck64.cpp`](https://github.com/mamedev/mame/blob/master/src/mame/nintendo/aleck64.cpp): chip list, CRCs, byte order and the 0x67C patch
- [`ipl3checksum`](https://pypi.org/project/ipl3checksum/): CIC-NUS-5101 seed and checksum algorithm
- [n64brew ROM Header](https://n64brew.dev/wiki/ROM_Header): ED64 advanced header
