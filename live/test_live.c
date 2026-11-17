#include "live_codec.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static LiveScratch scratch;
static uint16_t pixels[400*240];
static uint8_t data[40000],rgb[400*240*3];
int main(void) {
    for(unsigned w=320;w<=400;w+=80) {
        for(unsigned i=0;i<w*240;i++)pixels[i]=(uint16_t)(i*1777u);
        size_t minimum=12+w*240/64*7;
        assert(!live_encode(&scratch,pixels,w,240,minimum-1,data,sizeof data));
        for(size_t budget=minimum;budget<=25000;budget+=137) {
            size_t n=live_encode(&scratch,pixels,w,240,budget,data,sizeof data);
            assert(n>=minimum&&n<=budget);
            assert(live_decode(data,n,rgb,sizeof rgb)==(int)(w*240*3));
            assert(live_decode(data,n-1,rgb,sizeof rgb)==-1);
        }
    }
    /* Known red top-left corner tests the 3DS rotated-memory transform. */
    memset(pixels,0,sizeof pixels);
    for(unsigned x=0;x<8;x++)for(unsigned y=232;y<240;y++)pixels[x*240+y]=0xf800;
    size_t n=live_encode(&scratch,pixels,400,240,22000,data,sizeof data);
    assert(live_decode(data,n,rgb,sizeof rgb)>0);
    assert(rgb[0]==255&&rgb[1]==0&&rgb[2]==0);
    assert(rgb[(239*400)*3]==0);
    data[12]=99;assert(live_decode(data,n,rgb,sizeof rgb)==-1);
    for(unsigned i=0;i<20000;i++) {
        size_t len=(i*13)%sizeof data;
        for(size_t j=0;j<len;j++)data[j]=(uint8_t)rand();
        assert(live_decode(data,len,rgb,sizeof rgb)==-1);
    }
    puts("live codec: budget, dimensions, truncation, rotation, malformed input OK");
    return 0;
}
