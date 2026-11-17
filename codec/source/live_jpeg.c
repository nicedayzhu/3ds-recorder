/* Adapter to Apache-2.0 JPEGENC. Upstream remains an unmodified, pinned submodule. */
#define __LINUX__ 1
#include "../../third_party/JPEGENC/src/JPEGENC.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#include "../../third_party/JPEGENC/src/jpegenc.inl"
#pragma GCC diagnostic pop
#include "live_jpeg.h"
static JPEGE_IMAGE image;
/* Upstream reserves 512 bytes ahead of each MCU. Separate physical headroom
 * from the network budget, otherwise a JPEG that fits can fail prematurely. */
static uint8_t staging[40000+1024];
size_t live_jpeg_encode(const uint16_t *src,unsigned w,unsigned h,unsigned quality,uint8_t *out,size_t cap) {
    if(!src||!out||h!=240||(w!=400&&w!=320)||quality>3||cap<1024||cap>40000)return 0;
    memset(&image,0,sizeof image);
    image.pOutput=staging;image.iBufferSize=(int)cap+1024;image.pHighWater=staging+cap+512;
    JPEGENCODE enc;
    if(JPEGEncodeBegin(&image,&enc,(int)w,(int)h,JPEGE_PIXEL_RGB565,JPEGE_SUBSAMPLE_420,(uint8_t)quality))return 0;
    uint16_t tile[256];
    for(unsigned y=0;y<h;y+=16)for(unsigned x=0;x<w;x+=16) {
        for(unsigned dy=0;dy<16;dy++)for(unsigned dx=0;dx<16;dx++)tile[dy*16+dx]=src[(x+dx)*h+h-1-y-dy];
        if(JPEGAddMCU(&image,&enc,(uint8_t*)tile,32))return 0;
    }
    int size=JPEGEncodeEnd(&image);
    if(size<=0||(size_t)size>cap)return 0;
    memcpy(out,staging,(size_t)size);
    return (size_t)size;
}
