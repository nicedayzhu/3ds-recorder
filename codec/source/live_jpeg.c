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
static int scaled_tables(unsigned quality) {
    uint8_t tables[128];
    unsigned scale=quality<50?5000/quality:200-2*quality;
    for(unsigned i=0;i<128;i++) {
        unsigned value=((i<64?quant_lum[i]:quant_color[i-64])*scale+50)/100;
        tables[i]=(uint8_t)(value<1?1:value>255?255:value);
        image.sQuantTable[i]=tables[i];
    }
    /* Patch both on-wire DQT segments before entropy coding. The pinned library
     * stores quant_lum/quant_color in zigzag order, as required by JPEG DQT. */
    size_t end=(size_t)(image.pc.pOut-staging),at=2;unsigned found=0;
    while(at+4<=end && staging[at]==0xff) {
        unsigned marker=staging[at+1],len=(staging[at+2]<<8)|staging[at+3];
        if(len<2 || at+2+len>end)return 0;
        if(marker==0xda)break;
        if(marker==0xdb) {
            if(len!=67 || staging[at+4]>1)return 0;
            memcpy(staging+at+5,tables+64*staging[at+4],64);found++;
        }
        at+=2+len;
    }
    if(found!=2)return 0;
    JPEGFixQuantE(&image);
    return 1;
}
static size_t encode(const uint16_t *src,unsigned w,unsigned h,unsigned quality,
                     unsigned scaled,uint8_t *out,size_t cap) {
    if(!src||!out||h!=240||(w!=400&&w!=320)||cap<1024||cap>40000)return 0;
    memset(&image,0,sizeof image);
    image.pOutput=staging;image.iBufferSize=(int)cap+1024;image.pHighWater=staging+cap+512;
    JPEGENCODE enc;
    if(JPEGEncodeBegin(&image,&enc,(int)w,(int)h,JPEGE_PIXEL_RGB565,JPEGE_SUBSAMPLE_420,(uint8_t)quality))return 0;
    if(scaled && !scaled_tables(scaled))return 0;
    _Alignas(4) uint16_t tile[256]={0};
    for(unsigned y=0;y<h;y+=16)for(unsigned x=0;x<w;x+=16) {
        for(unsigned dy=0;dy<16;dy++)for(unsigned dx=0;dx<16;dx++)tile[dy*16+dx]=src[(x+dx)*h+h-1-y-dy];
        if(JPEGAddMCU(&image,&enc,(uint8_t*)tile,32))return 0;
    }
    int size=JPEGEncodeEnd(&image);
    if(size<=0||(size_t)size>cap)return 0;
    memcpy(out,staging,(size_t)size);
    return (size_t)size;
}
size_t live_jpeg_encode(const uint16_t *src,unsigned w,unsigned h,unsigned quality,uint8_t *out,size_t cap) {
    if(quality>3)return 0;
    return encode(src,w,h,quality,0,out,cap);
}
size_t live_jpeg_encode_scaled(const uint16_t *src,unsigned w,unsigned h,unsigned quality,uint8_t *out,size_t cap) {
    if(quality<1||quality>95)return 0;
    return encode(src,w,h,JPEGE_Q_MED,quality,out,cap);
}
