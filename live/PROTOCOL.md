# R6/R7 paired transport and legacy R3LP (experimental)

## R7 capability extension

R7 keeps the R3P2/R3F2 header and R6CF command layout. Valid device FPS are
15, 20, 24, 30; the fixed rate range is 400000..2000000 IPv4 B/s. The maximum
single-screen JPEG length is 128000 bytes (R6: 40000). This is a parser/allocation
bound, not permission to exceed the shared per-pair budget. Legacy R3LP remains
limited to 40000 bytes and 24/30 FPS.

Once per second R7 sends a **76-byte R7ST** packet: magic, the same 16 uint32
fields listed under R5 status below, then maximum supported rate (2000000) and
FPS mask `(1<<15)|(1<<20)|(1<<24)|(1<<30)`. All fields are little-endian. The
sender charges 104 IPv4 bytes for this status packet. No R3ST is sent in parallel.

The R7 receiver recognizes both R3ST and R7ST. For an R6 paired sender, R3ST
implies maximum rate 1000000 and FPS mask `(1<<24)|(1<<30)`; the UI restricts
choices accordingly. Capability fields are appended to CSV as `sender_max_rate`
and `sender_fps_mask`. R7 retains the R6CF magic so the new PC can control R6.
Old PC receivers cannot use R7's larger frames/new FPS and must be upgraded.
Controls are runtime-only and still applied between pairs with an epoch change.

The header's FPS is the configured paired sampling rate. It does not establish
the game's render rate, and source reuse can still occur. No 60 FPS capability
is advertised. New rates/FPS require hardware validation beyond host tests.

## R6 / R3P2

R6 sends independently decodable JPEGs in pairs. The 32-byte header below keeps
its layout but uses `R3P2`; sequence and PTS are common to both screens. PTS is
the composite sampling clock, not proof of simultaneous game rendering. The
capture tracker may retain a non-swapping framebuffer; source reuse is logged.

Each screen additionally sends two `R3F2` packets with the same metadata. Their
offset field is the stripe index (0 or 1); payload is exactly 1168 bytes. Stripe
g XORs zero-padded data fragments with fragment_index % 2 == g. One missing data
fragment per stripe is recoverable if that parity packet and the other stripe
members arrive. Two missing fragments in the same stripe are not recoverable.
Data packets alternate screens; parity packets follow, also alternating screens.
There is no retransmission or cross-pair decoding reference.

The receiver retains at most two incomplete pairs, expires them after 80 ms and
never presents an older sequence after a newer one. Both JPEGs must decode before
either display changes. A late or unrecoverable pair is skipped as a unit.

For each pair the sender reserves 4% of rate/fps, then accounts for four parity
packets, JPEG bytes and every fragment's 60-byte application/IPv4/UDP overhead.
Status packets use the same pacer. Exact calculations and all screen byte splits
are checked in `test_pair.c`. This is a fixed cap without padding to fill idle
bandwidth; Wi-Fi MAC retransmissions/airtime are not included. Packet-boundary
tolerance still applies to arbitrary short measurement intervals.

`R6CF` is a 20-byte little-endian control packet: magic, session, request sequence,
FPS (24 or 30), rate (620000..1000000 B/s). It must originate from the configured
receiver IP and UDP port. New settings are applied between sending pairs; a
configuration epoch discards queued/encoding pairs from the previous settings.
The capture loop reads the updated FPS. `R3ST` reports the actual settings; the
receiver retries a request for at most five seconds. Runtime settings are not
written to SD. `R3FB` is counted for diagnostics but never changes R6's budget.

JPEG preparation caches exact RGB565 MCU tiles and unquantized DCT coefficients.
Unchanged tiles skip conversion/DCT; quantization and entropy coding still emit
a complete JPEG. The two workers share a quality parameter and total budget.
There are at most three entropy passes per pair, with Q1 as the final emergency
attempt; failure drops the whole pair. No temporal coefficients are transmitted.

## Legacy R3LP version 1

UDP payload is at most 1200 bytes: a 32-byte little-endian header followed by at most 1168 bytes of frame data. There is no negotiation, encryption, authentication, retransmission or audio. Use a trusted local network; the receiver restricts the source IP and the RTSP server binds loopback.

| Offset | Field | Meaning |
|---|---|---|
| 0 | char[4] | `R3LP` |
| 4 | uint32 | Session ID, low system tick word at sender start |
| 8 | uint32 | Global frame sequence, increments for either screen, wraps |
| 12 | uint32 | Capture PTS in microseconds from stream start, wraps |
| 16 | uint32 | Screen: 0 top / 1 bottom |
| 20 | uint32 | Total encoded frame bytes, <=40000 |
| 24 | uint32 | Fragment byte offset, multiple of 1168 |
| 28 | uint32 | Configured output FPS, 24 or 30 |

The payload starts with JPEG SOI (`FF D8`) or `LTC1`. Top dimensions must be 400×240; bottom 320×240. A frame is independently decodable. The receiver retains at most one incomplete frame per screen, expires it after 150 ms, and accepts only a newer modulo-32-bit sequence. A session change starts at fragment zero; the last 16 retired sessions are rejected. Source address filtering is not cryptographic authentication. PTS is checked for fragment consistency but not used for clock synchronization in this prototype; screens display independently as they arrive.

LTC1 begins with 12 bytes: magic, uint16 width, uint16 height, uint16 tile count, uint16 zero reserved. Then raster-order 8×8 tiles. Mode 0 uses a 2×2-averaged 4×4 two-color bitmap (7 bytes/tile); mode 1 an 8×8 two-color bitmap (13); mode 2 four 4×4 two-color bitmaps (25). Each bitmap holds two little-endian RGB565 endpoints followed by little-bit-order selectors. Mode 0 expands each sample to 2×2 pixels. All tiles have a baseline representation, then a max heap assigns remaining bytes to distortion-reducing upgrades. There are no delta frames or reference state.

Encoder input is the 3DS column-major, vertically reversed RGB565 layout. Decoder output is row-major RGB24. `live_jpeg_encode_screen` owns two separate states; one producer per screen may call it concurrently. The legacy JPEG entry points share state 0 and must not race with screen 0. The C decoder validates the entire LTC1 length and tile layout before writing output pixels.

Sender spacing charges each packet `payload + 28` bytes, including IPv4/UDP. Encoding budgets reserve 7% of the configured rate for headers. Delays do not accumulate send credit, so an idle period does not authorize a later burst. The first packet and scheduler quantization allow roughly one packet of interval-edge tolerance; this is a paced average limit, not a guarantee about physical Wi-Fi airtime or every arbitrary microsecond window. A frame that cannot be sent within one configured frame period is abandoned. Sender counters count fully submitted frames, not acknowledgments from the PC.

## R5 feedback and live status

Video remains R3LP over UDP, with no retransmission. Once per second the sender also emits a 68-byte little-endian `R3ST` packet: magic followed by 16 uint32 fields: session, elapsed milliseconds, wire-rate cap, encoder-rate budget, FPS, encoded top/bottom, sent top/bottom, send errors, expired frames, accepted feedback count, encoder core top/bottom, latest encode microseconds top/bottom. Its IPv4/UDP overhead is included in sender pacing. These counters allow live diagnosis without stopping to read SD logs.

The receiver replies from its existing UDP port to the sender's source port with a 28-byte `R3FB` packet: magic, session, monotonically increasing sequence, cumulative received video packets, cumulative decoded frames (both screens), cumulative incomplete frames, relative arrival-delay growth in milliseconds. The sender checks source IP/port, session, size and sequence, accepts at most two updates per second, and handles receiver counter resets. This filtering is not cryptographic authentication.

With `adaptive=on`, the encoder budget starts at min(cap, 800,000 B/s), can decrease to 400,000 B/s, and never exceeds the configured wire cap. Missing-frame/packet feedback or delay growth reduces the budget; three clean observations permit a 2.5% increase. Capture FPS stays configured. Lower budgets proactively lower JPEG quality when the previous image would not fit. This is experimental congestion control, not a guarantee of frame rate, quality or latency on a lossy network. Without feedback it keeps the current budget; it does not infer delivery from successful `sendto` calls.
