#include "live_stream.h"
#include "live_codec.h"
#include "live_jpeg.h"
#include "live_pacing.h"
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
/* JPEG-only is the live default. LTC1 remains an explicit diagnostic choice. */
static unsigned codecMode; /* 0 JPEG, 1 legacy hybrid, 2 LTC1 */
static unsigned quality[2]={60,60},spare[2];
static u32 frames[2],replaced,errors;
static u32 attempts[2],jpegFrames[2],ltcFrames[2],oversize[2],maxUs[2],maxBytes[2];
static u64 sumUs[2],started;
static u32 expired;
static int lastErrno;
static u32 sendCalls,sendMaxUs;
static u64 sendSumUs;

bool live_requested(void) {
    enabled=false;fps=30;rate=700000;codecMode=0;
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
        else if(!strcmp(key,"codec"))codecMode=!strcmp(val,"ltc1")?2:!strcmp(val,"hybrid")?1:0;
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
            if(now>deadline){expired++;break;}
            if(due>now)svcSleepThread((due-now)*1000000000ull/SYSCLOCK_ARM11);
            if(svcGetSystemTick()>deadline){expired++;break;}
            memcpy(packet,"R3LP",4);put32(packet+4,session);put32(packet+8,seq);put32(packet+12,stamp);
            put32(packet+16,sc);put32(packet+20,n);put32(packet+24,off);put32(packet+28,fps);
            memcpy(packet+32,sending+off,len);
            u64 sendStart=svcGetSystemTick();
            int sent=sendto(fd,packet,len+32,0,(struct sockaddr*)&target,sizeof target);
            u32 sendUs=(u32)((svcGetSystemTick()-sendStart)*1000000/SYSCLOCK_ARM11);
            sendCalls++;sendSumUs+=sendUs;if(sendUs>sendMaxUs)sendMaxUs=sendUs;
            /* Includes IPv4+UDP headers; no claim to bound Wi-Fi retransmission airtime. */
            due=live_packet_due(due,sendStart,len+60,rate,SYSCLOCK_ARM11);
            if(sent!=(int)(len+32)){lastErrno=errno;errors++;break;}
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
    replaced=errors=expired=0;lastErrno=0;quality[0]=quality[1]=60;spare[0]=spare[1]=0;
    sendCalls=sendMaxUs=0;sendSumUs=0;
    memset(attempts,0,sizeof attempts);memset(jpegFrames,0,sizeof jpegFrames);memset(ltcFrames,0,sizeof ltcFrames);
    memset(oversize,0,sizeof oversize);memset(sumUs,0,sizeof sumUs);memset(maxUs,0,sizeof maxUs);memset(maxBytes,0,sizeof maxBytes);
    started=svcGetSystemTick();
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
                  frames[0],frames[1],replaced,errors,rate,fps);
        fprintf(f,"duration_ms=%llu\nexpired_frames=%lu\nlast_send_errno=%d\ncodec_mode=%u\n",
                (svcGetSystemTick()-started)*1000/SYSCLOCK_ARM11,expired,lastErrno,codecMode);
        fprintf(f,"send_calls=%lu\nsend_mean_us=%llu\nsend_max_us=%lu\n",sendCalls,
                sendCalls?sendSumUs/sendCalls:0,sendMaxUs);
        for(unsigned sc=0;sc<2;sc++)fprintf(f,
            "screen%u_attempts=%lu\nscreen%u_jpeg=%lu\nscreen%u_ltc1=%lu\nscreen%u_oversize=%lu\n"
            "screen%u_encode_mean_us=%llu\nscreen%u_encode_max_us=%lu\nscreen%u_max_bytes=%lu\nscreen%u_quality=%u\n",
            sc,attempts[sc],sc,jpegFrames[sc],sc,ltcFrames[sc],sc,oversize[sc],
            sc,attempts[sc]?sumUs[sc]/attempts[sc]:0,sc,maxUs[sc],sc,maxBytes[sc],sc,quality[sc]);
        fclose(f);}
}
bool live_submit(int sc,const u8 *frame,u32 fmt,u32 stride,u32 pts,bool wide) {
    if(sc<0||sc>1||!worker||stopping||wide)return false;
    u64 begin=svcGetSystemTick();
    u32 w=sc?320:400;
    if(!fb_to_rgb565(rgb565,frame,fmt,w,240,stride,1))return false;
    size_t budget=(rate*93/100/fps)*w/720;
    size_t n=codecMode==2?0:live_jpeg_encode_scaled(rgb565,w,240,quality[sc],encoded,budget);
    if(codecMode!=2) {
        if(!n){oversize[sc]++;quality[sc]=quality[sc]>16?quality[sc]-6:10;spare[sc]=0;}
        else if(n<budget*9/10){if(++spare[sc]>=8){if(quality[sc]<85)quality[sc]++;spare[sc]=0;}}
        else spare[sc]=0;
    }
    if(n)jpegFrames[sc]++;
    if(!n && codecMode!=0){n=live_encode(&scratch,rgb565,w,240,budget,encoded,sizeof encoded);if(n)ltcFrames[sc]++;}
    u32 us=(u32)((svcGetSystemTick()-begin)*1000000/SYSCLOCK_ARM11);
    attempts[sc]++;sumUs[sc]+=us;if(us>maxUs[sc])maxUs[sc]=us;
    if(n>maxBytes[sc])maxBytes[sc]=(u32)n;
    if(!n)return false;
    LightLock_Lock(&lock);
    if(lengths[sc])replaced++;
    memcpy(pending[sc],encoded,n);lengths[sc]=(u32)n;stamps[sc]=pts;
    LightLock_Unlock(&lock);
    return true;
}
