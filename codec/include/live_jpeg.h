#ifndef LIVE_JPEG_H
#define LIVE_JPEG_H
#include <stddef.h>
#include <stdint.h>
/* Single encoder thread. quality 0=best .. 3=low; 0 on overflow/failure. */
size_t live_jpeg_encode(const uint16_t *column_rgb565,unsigned width,unsigned height,
                        unsigned quality,uint8_t *out,size_t capacity);
#endif
