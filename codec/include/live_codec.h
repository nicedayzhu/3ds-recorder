#ifndef LIVE_CODEC_H
#define LIVE_CODEC_H
#include <stddef.h>
#include <stdint.h>
#define LIVE_MAX_TILES 1500
#define LIVE_MAX_FRAME 40000
/* Independently decodable 8x8 tiles; column-major RGB565 input, bottom to top.
 * Scratch is caller owned, reused across screens; no heap or floating point. */
typedef struct {
    uint8_t data[LIVE_MAX_TILES][25];
    uint16_t order[LIVE_MAX_TILES];
    uint32_t gain[LIVE_MAX_TILES];
    uint8_t base[LIVE_MAX_TILES][7];
} LiveScratch;
size_t live_encode(LiveScratch *scratch, const uint16_t *src, unsigned width,
                   unsigned height, size_t budget, uint8_t *out, size_t capacity);
/* RGB24 row-major output; rejects malformed input before writing pixels. */
int live_decode(const uint8_t *src, size_t size, uint8_t *rgb, size_t capacity);
#endif
