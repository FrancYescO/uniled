# SP661E / SP662E (BanlanX) BLE protocol notes

Reverse-engineered from a single-colour SP661E PWM controller and two CCT SP662E PWM controllers
(all firmware string `V1.0.02`). Everything marked **verified** was confirmed on real hardware
(state read-back and/or visually on the LED strip). Everything else is a hypothesis.

## 1. Device and BLE layout

| Item | Value |
|---|---|
| Advertised name | `LMB` (SP661E unit tested) or `SP662E` (both SP662E units tested) |
| Manufacturer data | company id `0x5053` ("SP"), 12-byte payload `01 00 <model> <6-byte MAC> 00 00 00` — `<model>` is `7a` on SP661E (`01 00 7a 5c 12 30 62 d3 ea 00 00 00`) and `7b` on SP662E (`01 00 7b b4 20 1d 32 1b 0a 00 00 00`) |
| Advertised service | `0xE0FF` |
| Control service | `0000ffe0-0000-1000-8000-00805f9b34fb` |
| Control characteristic | `0000ffe1-...` (write, write-without-response, notify) |
| OTA service | `5833ff01-9b8b-5191-6142-22a4536ef123`: **never write to it** (firmware update channel) |

Only one BLE connection is accepted at a time (phone app *or* host, not both). The controller does
not push state on its own: enable notifications on FFE1 and send a state query.

Before the dedicated `SP661E` model existed, UniLED matched this device by manufacturer-data
byte `0x01` and treated it as an SP601E (SPI controller), which sends `AA 2F 00`; the SP661E
ignores that, so setup failed with `device update failed`.

The `01 00` prefix is not an exclusive SP661E signature: SP601E units may share it.
When the advertised model name cannot resolve the ambiguity, UniLED queries the
candidate protocols during setup and saves the model that responds successfully.
Existing entries saved as SP601E retain their model; recreate an incorrectly
identified SP661E entry to trigger protocol detection. The SP661E speaks the "6xx" framing
(below) but with a different state layout and different command payloads than the SP63xE code.

Note: the controller only answers a state query that is written **without response**
(`write_without_response`). A write with response is accepted but never answered.

## 2. Frame format

```
53 CMD 00 01 00 LEN DATA[LEN]
```

`53` header, `CMD` command, `00` key (unencrypted), `01 00` constant, `LEN` payload length.
Responses use the same framing on FFE1 notifications. Write without response works.

**BanlanX app obfuscation (verified from HCI capture):** the official phone app sends a non-zero
random `KEY` in byte `[2]` and XOR-encodes every payload byte as
`encoded = plaintext ^ KEY ^ <model>` (where `<model>` is manufacturer-data byte `[2]`, e.g.
`0x7B` on SP662E). Both SP661E and SP662E accept unencrypted `KEY = 0x00` frames directly, so
UniLED does not need to encode outgoing packets.

## 3. Commands (all verified unless noted)

Most control commands take a payload that starts with `01` (channel 1); CCT commands (`0x60`/`0x61`)
carry `[cold, warm]` directly with no channel prefix.

| Action | Frame | Notes |
|---|---|---|
| Query state | `53 02 00 01 00 01 01` | reply is `53 02 ...`, 98-108 bytes |
| On/off speed | `53 08 00 01 00 05 00 EE SS 00 01` | `EE` = on/off effect (`03` gradient), `SS` = `01` Slow / `02` Medium / `03` Fast (verified from BanlanX HCI capture; readback at `[23..24]`) |
| Power-on state | `53 0b 00 01 00 01 MM` | `MM` = `00` Light Off / `01` Light On / `02` Last state (verified from BanlanX HCI capture; readback at `[22]`, no leading `01` channel byte) |
| Power cycle reset | `53 17 00 01 00 03 DD 07 05` | `DD` = `01` Off (disabled) / `00` On (enabled); verified from BanlanX HCI capture (status readback offset not yet isolated) |
| Power on | `53 50 00 01 00 02 01 01` | verified on SP661E and SP662E |
| Power off | `53 50 00 01 00 02 01 00` | verified on SP661E and SP662E |
| Brightness | `53 51 00 01 00 03 01 80 LL` | `LL` 0-255, linear (remote steps: 10%=`1a`, 20%=`33`, 30%=`4d`, 50%=`80`, 80%=`cc`, 100%=`ff`). Verified on SP661E and SP662E (note: BanlanX app sends `01` instead of `80` in the selector byte, i.e. `01 01 LL`; both update `[51]` independently of CCT `[55..56]`) |
| Secondary level | `53 51 00 01 00 03 01 00 LL` | sets state byte `[50]`; no visible effect identified |
| Mode / effect | `53 53 00 01 00 03 01 MM EE` | see section 4 |
| Effect speed | `53 54 00 01 00 02 01 SS` | `SS` 00-0a accepted; `80` ignored; higher is faster |
| Static CCT (SP662E) | `53 61 00 01 00 02 CC WW` | **verified** live on SP662E (`00 ff`, `9e 61`, `dc 23`, `ff 00` all reflected verbatim at `[55..56]`). `CC` (cold) + `WW` (warm) = 255; no leading `01` channel byte |
| Effect CCT (SP662E) | `53 60 00 01 00 02 CC WW` | dynamic-mode CCT (hypothesis matching SPTech `EFFECT_CCT`) |

Pitfall: a two-byte brightness payload (`01 LL`) sets the level to 0 (strip drops to minimum). The
level is always the **last** byte, and the byte before it selects the field (`80` = brightness).

## 4. Modes

| `MM` | `EE` | Result |
|---|---|---|
| `02` | `01` | solid colour (default mode) |
| `04` | `01` | triangle (smooth ramp) |
| `04` | `02` | strobe |
| `04` | `03` | heartbeat |
| `06` | `01` | music mode: selectable, but no reaction to sound; the unit has no microphone, so audio is probably streamed by the phone app (not investigated) |

Effects 01-03 were identified visually in the order the RF remote cycles them.

## 5. State reply layout (offsets in the full notification, header included)

The 104-byte status reply (`len = 0x62` + 6-byte header) uses standard SPTech 2-byte-length chunks:
Chunk 10 (`0a 00 1c` at `[7]`), Chunk 3 (`03 00 2a` at `[38]`), Chunk 12 (`0c 00 0c` at `[83]`),
and Chunk 13 (`0d 00 03` at `[98]`).

| Offset | Meaning |
|---|---|
| `[5]` | payload length (`0x62` normal; changes if the device changes internal mode) |
| `[13..19]` | firmware string (`V1.0.02`) |
| `[20]` | hardware/model byte (`0x63` on SP661E, `0x72` on both SP662E units) |
| `[22]` | power-on restore state (`00` Light Off, `01` Light On, `02` Last state) — **verified** |
| `[23]` | on/off transition effect (`03` gradient) |
| `[24]` | on/off transition speed (`01` Slow, `02` Medium, `03` Fast) — **verified** |
| `[30..35]` | paired RF remote ID (`00 00 00 00 00 00` when unpaired) |
| `[42]` | light type (`01` PWM single-colour SP661E, `03` PWM CCT SP662E) — **verified** |
| `[44]` | power (`01` on, `00` off) — **verified** |
| `[47]` | mode (`02` solid, `04` dynamic, `06` music) — **verified** |
| `[48]` | effect number — **verified** |
| `[50]` | secondary level (effect brightness) |
| `[51]` | solid brightness 0-255 (in animated modes this is the *current output* and oscillates, so do not treat it as the setting) — **verified** |
| `[55..56]` | static CCT `(cold, warm)` summing to 255 on SP662E (`ff 00` on SP661E) — **verified** |
| `[57]` | effect speed — **verified** |
| `[65..66]` | effect CCT `(cold, warm)` summing to 255 on SP662E (`ff 00` on SP661E) |

Other bytes were not decoded. Offsets differ from UniLED's SP63xE parser because SP66xE precedes
Chunk 3 with Chunk 10 (`0x0a`) instead of Chunk 1 (`0x01`) (e.g. power is `[44]`, not `[29]`).

## 6. Dangerous / unexplored commands

Found while probing with a blind sweep. They modify device configuration, so avoid them:

- `0x5E` rewrites about 40 state bytes at once (looks like a reset). After it the RF remote lost
  its pairing and had to be re-paired.
- `0x0A`, `0x0D`, `0x30`, `0x57`, `0x58`, `0x59`, `0x5A` each change an
  unidentified setting or flag (`0x08` = on/off speed, `0x0B` = power-on state, `0x17` = power
  cycle reset; documented in section 3). `0x6A`/`0x6B` (light type, channel order in related
  models) were deliberately never sent.
- Sending an arbitrary mode number to `0x53` (for example `80`) leaves the device in an undefined mode.

The RF remote can be re-paired by powering the controller on and long-pressing ON on the remote
within about 20 s (documented for sibling BanlanX models, not checked against an SP661E manual).

## 7. Not investigated

- Timers (the RF remote has a 15/30/45/0 timer button, but pressing it produced no state change).
- Music mode audio input.
- RGB / RGBW / RGBCCT variants (`SP663E`/`SP664E`/`SP665E`).
- Dynamic-mode CCT (`0x60`) live readback on SP662E (`[65..66]`), and the BanlanX app's initial `0x6D` (`01 01 02 01`) pre-command.

Dynamic-mode brightness uses the secondary level at `[50]` as the requested
setting; its visual effect has not been confirmed. Music mode and timers are not
exposed by this integration.
