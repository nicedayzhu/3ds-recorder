#ifndef LIVE_JPEG_H
#define LIVE_JPEG_H
#include <stddef.h>
#include <stdint.h>
/* Legacy entry points use screen/context 0. quality 0=best .. 3=low. */
size_t live_jpeg_encode(const uint16_t *column_rgb565,unsigned width,unsigned height,
                        unsigned quality,uint8_t *out,size_t capacity);
/* Fine-grained JPEG quality 1..95. Same rotation and strict output capacity. */
size_t live_jpeg_encode_scaled(const uint16_t *column_rgb565,unsigned width,unsigned height,
                               unsigned quality,uint8_t *out,size_t capacity);
/* Two independent states; one producer per screen. 0 on overflow/failure.
 * Calls for different screens may run concurrently. */
size_t live_jpeg_encode_screen(unsigned screen,const uint16_t *column_rgb565,unsigned width,unsigned height,
                               unsigned quality,uint8_t *out,size_t capacity);
#endif
