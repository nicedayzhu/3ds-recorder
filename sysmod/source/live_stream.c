#include "live_stream.h"
#include "live_codec.h"
#include "live_jpeg.h"
#include "convert.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

/* One producer (the recorder converter), one network worker. No unbounded queue.
 * The worker alone owns the socket; a stopped worker is joined before SOC exits. */
static LiveScratch scratch;
static u16 rgb565[400*240];
static u8 encoded[LIVE_MAX_FRAME],pending[2][LIVE_MAX_FRAME],sending[LIVE_MAX_FRAME];
static u32 lengths[2],stamps[2],sequence,session;
static LightLock lock;
static Thread worker;
static int fd=-1;
static u32 *socbuf;
static u32 socStorage[0x100000/sizeof(u32)] __attribute__((aligned(0x1000)));
static bool socReady;
static volatile bool stopping;
static struct sockaddr_in target;
static u32 fps=30,rate=700000;
static bool enabled;
static bool hybrid=true;
static unsigned quality[2]={2,2},spare[2];
static u32 frames[2],replaced,errors;

bool live_requested(void) {
    enabled=false;fps=30;rate=700000;hybrid=true;
    FILE *f=fopen("sdmc:/3ds/recorder/live.ini","r");
    if(!f)return false;
    char line[128],ip[64]="";unsigned port=8001;
    while(fgets(line,sizeof line,f)) {
        char key[40],val[64];if(sscanf(line,"%39[^=]=%63s",key,val)!=2)continue;
        if(!strcmp(key,"enabled"))enabled=!strcmp(val,"on");
        else if(!strcmp(key,"host"))snprintf(ip,sizeof ip,"%s",val);
        else if(!strcmp(key,"port"))port=(unsigned)strtoul(val,NULL,10);
        else if(!strcmp(key,"fps"))fps=(u32)strtoul(val,NULL,10);
        else if(!strcmp(key,"bytes_per_second"))rate=(u32)strtoul(val,NULL,10);
        else if(!strcmp(key,"codec"))hybrid=strcmp(val,"ltc1")!=0;
    }
    fclose(f);
    memset(&target,0,sizeof target);target.sin_family=AF_INET;
    if(port<1||port>65535||inet_pton(AF_INET,ip,&target.sin_addr)!=1)enabled=false;
    target.sin_port=htons((u16)port);
    if(fps!=24&&fps!=30)enabled=false;
    if(rate<620000||rate>1000000)enabled=false;
    return enabled;
}
u32 live_fps(void){return fps;}
static void put32(u8 *p,u32 n){for(unsigned i=0;i<4;i++)p[i]=(u8)(n>>(8*i));}
static void sender(void *unused) {
    (void)unused;unsigned next=0;
    u64 due=svcGetSystemTick();
    while(!__atomic_load_n(&stopping,__ATOMIC_ACQUIRE)) {
        u32 n=0,stamp=0,sc=0;
        LightLock_Lock(&lock);
        for(unsigned i=0;i<2;i++) {
            sc=(next+i)%2;n=lengths[sc];
            if(n){memcpy(sending,pending[sc],n);stamp=stamps[sc];lengths[sc]=0;next=sc^1;break;}
        }
        LightLock_Unlock(&lock);
        if(!n){svcSleepThread(1000000);continue;}
        u32 seq=++sequence;u64 deadline=svcGetSystemTick()+SYSCLOCK_ARM11/fps;
        for(u32 off=0;off<n&&!__atomic_load_n(&stopping,__ATOMIC_ACQUIRE);off+=1168) {
            u32 len=n-off>1168?1168:n-off;u8 packet[1200];
            u64 now=svcGetSystemTick();
            if(now>deadline)break;
            if(due>now)svcSleepThread((due-now)*1000000000ull/SYSCLOCK_ARM11);
            if(svcGetSystemTick()>deadline)break;
            memcpy(packet,"R3LP",4);put32(packet+4,session);put32(packet+8,seq);put32(packet+12,stamp);
            put32(packet+16,sc);put32(packet+20,n);put32(packet+24,off);put32(packet+28,fps);
            memcpy(packet+32,sending+off,len);
            int sent=sendto(fd,packet,len+32,0,(struct sockaddr*)&target,sizeof target);
            now=svcGetSystemTick();
            /* Includes IPv4+UDP headers; no claim to bound Wi-Fi retransmission airtime. */
            due=(now>due?now:due)+(u64)(len+60)*SYSCLOCK_ARM11/rate;
            if(sent!=(int)(len+32)){errors++;break;}
            if(off+len==n)frames[sc]++;
        }
    }
}
Result live_start(void) {
    if(worker)return -1;
    /* The module's malloc heap is 256 KB; SOC needs its own aligned area. */
    socbuf=socStorage;
    Result rc=socInit(socbuf,0x100000);
    if(R_FAILED(rc)){socbuf=NULL;return rc;}
    socReady=true;fd=socket(AF_INET,SOCK_DGRAM,0);
    if(fd<0){live_stop();return -3;}
    if(fcntl(fd,F_SETFL,O_NONBLOCK)<0){live_stop();return -4;}
    LightLock_Init(&lock);memset(lengths,0,sizeof lengths);memset(frames,0,sizeof frames);
    replaced=errors=0;quality[0]=quality[1]=2;spare[0]=spare[1]=0;
    session=(u32)svcGetSystemTick();sequence=0;stopping=false;
    worker=threadCreate(sender,NULL,8192,0x3E,1,false);
    if(!worker){live_stop();return -5;}
    return 0;
}
void live_stop(void) {
    __atomic_store_n(&stopping,true,__ATOMIC_RELEASE);
    if(worker){threadJoin(worker,U64_MAX);threadFree(worker);worker=NULL;}
    if(fd>=0){close(fd);fd=-1;}
    if(socReady){socExit();socReady=false;}
    socbuf=NULL;
    FILE *f=fopen("sdmc:/3ds/recorder/live-stats.txt","w");
    if(f){fprintf(f,"sent_top=%lu\nsent_bottom=%lu\nreplaced=%lu\nsend_errors=%lu\nrate=%lu\nfps=%lu\n",
                  frames[0],frames[1],replaced,errors,rate,fps);fclose(f);}
}
bool live_submit(int sc,const u8 *frame,u32 fmt,u32 stride,u32 pts,bool wide) {
    if(sc<0||sc>1||!worker||stopping||wide)return false;
    u32 w=sc?320:400;
    if(!fb_to_rgb565(rgb565,frame,fmt,w,240,stride,1))return false;
    size_t budget=(rate*93/100/fps)*w/720;
    size_t n=hybrid?live_jpeg_encode(rgb565,w,240,quality[sc],encoded,budget):0;
    if(hybrid) {
        if(!n){if(quality[sc]<3)quality[sc]++;spare[sc]=0;}
        else if(n<budget*6/10){if(++spare[sc]>=30){if(quality[sc])quality[sc]--;spare[sc]=0;}}
        else spare[sc]=0;
    }
    if(!n)n=live_encode(&scratch,rgb565,w,240,budget,encoded,sizeof encoded);
    if(!n)return false;
    LightLock_Lock(&lock);
    if(lengths[sc])replaced++;
    memcpy(pending[sc],encoded,n);lengths[sc]=(u32)n;stamps[sc]=pts;
    LightLock_Unlock(&lock);
    return true;
}
