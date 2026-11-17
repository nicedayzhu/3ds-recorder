#include <3ds.h>
#include <stdio.h>
#include "live_codec.h"
#include "live_jpeg.h"
static LiveScratch scratch;
static uint16_t pixels[400*240];
static uint8_t encoded[LIVE_MAX_FRAME];
int main(void) {
    gfxInitDefault();consoleInit(GFX_TOP,NULL);osSetSpeedupEnable(true);
    printf("Dual-screen live codec benchmark\nNew 3DS requested 804MHz\nNo game running; encoding only\n");
    FILE *f=fopen("sdmc:/live-bench.csv","w");
    if(f)fprintf(f,"codec,width,iteration,bytes,encode_us\n");
    for(unsigned w=400;w>=320;w-=80) {
        uint64_t sum=0,max=0;
        FILE *input=fopen(w==400?"sdmc:/live-bench-top.rgb565":"sdmc:/live-bench-bottom.rgb565","rb");
        bool real=input && fread(pixels,2,w*240,input)==w*240;
        if(input)fclose(input);
        if(!real)for(unsigned i=0;i<w*240;i++)pixels[i]=(uint16_t)(i*117);
        printf("%u input: %s\n",w,real?"SD sample":"synthetic");
        for(unsigned k=0;k<60;k++) {
            uint64_t start=svcGetSystemTick();
            size_t n=live_encode(&scratch,pixels,w,240,(700000u*93/100/30)*w/720,encoded,sizeof encoded);
            uint64_t us=(svcGetSystemTick()-start)*1000000/SYSCLOCK_ARM11;
            sum+=us;if(us>max)max=us;
            if(f)fprintf(f,"ltc1,%u,%u,%u,%llu\n",w,k,(unsigned)n,us);
        }
        printf("%u: mean %llu us max %llu us\n",w,sum/60,max);
        for(unsigned quality=0;quality<=3;quality++) {
        sum=max=0;
        for(unsigned k=0;k<60;k++) {
            uint64_t start=svcGetSystemTick();
            size_t n=live_jpeg_encode(pixels,w,240,quality,encoded,(700000u*93/100/30)*w/720);
            uint64_t us=(svcGetSystemTick()-start)*1000000/SYSCLOCK_ARM11;
            sum+=us;if(us>max)max=us;
            if(f)fprintf(f,"jpeg_q%u,%u,%u,%u,%llu\n",quality,w,k,(unsigned)n,us);
        }
        printf("JPEG q%u %u: %llu us max %llu\n",quality,w,sum/60,max);
        }
        for(unsigned quality=2;quality<=3;quality++) {
            sum=max=0;
            for(unsigned k=0;k<60;k++) {
                uint64_t start=svcGetSystemTick();
                unsigned budget=(700000u*93/100/30)*w/720;
                size_t n=live_jpeg_encode(pixels,w,240,quality,encoded,budget);
                if(!n)n=live_encode(&scratch,pixels,w,240,budget,encoded,sizeof encoded);
                uint64_t us=(svcGetSystemTick()-start)*1000000/SYSCLOCK_ARM11;
                sum+=us;if(us>max)max=us;
                if(f)fprintf(f,"hybrid_q%u,%u,%u,%u,%llu\n",quality,w,k,(unsigned)n,us);
            }
            printf("Hybrid q%u %u: %llu max %llu us\n",quality,w,sum/60,max);
        }
    }
    if(f)fclose(f);
    puts("CSV: /live-bench.csv\nSTART to exit");
    while(aptMainLoop()) {hidScanInput();if(hidKeysDown()&KEY_START)break;gspWaitForVBlank();}
    gfxExit();return 0;
}
