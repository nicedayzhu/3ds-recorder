#include "live_stream.h"
#include "live_jpeg.h"
#include "live_pacing.h"
#include "live_pair.h"
#include "convert.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

/* Encoder 0 coordinates pairs, encoder 1 handles bottom. The socket worker
 * owns rate changes and one latest complete pair. No temporal wire dependency. */
#define MAX_JPEG LIVE_JPEG_MAX_BYTES
static u16 rgb565[400*240],rawPending[2][400*240],rawWorking[2][400*240];
static u8 encoded[2][MAX_JPEG],pending[2][MAX_JPEG],sending[2][MAX_JPEG];
static bool rawValid[2],pendingReady,enabled,socReady;
static volatile bool stopping;
static u32 rawPts[2],planPts[2],planStamp,planMask;
static u32 pendingLengths[2],pendingSeq,pendingStamp,pendingEpoch,sequence,session;
static u64 pendingAt,started;
static LightLock lock;
static LightEvent events[3];
static Thread worker,encoders[2];
static s32 encoderCores[2];
static int fd=-1,lastErrno;
static u32 socStorage[0x100000/4] __attribute__((aligned(0x1000)));
static struct sockaddr_in target;
static u32 fps=30,rate=800000,configEpoch,configSequence;
static unsigned quality=60,spare;
static u32 jobKind,jobQuality,jobDone,jobSize[2],jobChanged[2],jobUs[2];
static u32 attempts[2],jpegFrames[2],maxUs[2],maxBytes[2],convertCount[2],convertMaxUs[2];
static u64 sumUs[2],convertSumUs[2],changedMcus[2];
static u32 sourceReuse[2],lastSource[2],frames[2],replaced,errors,expired,oversize,retries,pairs;
static u32 sendCalls,sendMaxUs,lastEncodeUs[2],feedbackCount,configChanges;
static u64 sendSumUs,lastStatusTick,lastControlTick;
static u32 get32(const u8 *p){return (u32)p[0]|(u32)p[1]<<8|(u32)p[2]<<16|(u32)p[3]<<24;}
static void put32(u8 *p,u32 n){for(unsigned i=0;i<4;i++)p[i]=(u8)(n>>(8*i));}
static bool stopped(void){return __atomic_load_n(&stopping,__ATOMIC_ACQUIRE);}
bool live_requested(void) {
    if(worker)return enabled;
    enabled=false;fps=30;rate=800000;
    FILE *f=fopen("sdmc:/3ds/recorder/live.ini","r");if(!f)return false;
    char line[128],ip[64]="";unsigned port=8001;
    while(fgets(line,sizeof line,f)) {
        char key[40],val[64];if(sscanf(line,"%39[^=]=%63s",key,val)!=2)continue;
        if(!strcmp(key,"enabled"))enabled=!strcmp(val,"on");
        else if(!strcmp(key,"host"))snprintf(ip,sizeof ip,"%s",val);
        else if(!strcmp(key,"port"))port=(unsigned)strtoul(val,NULL,10);
        else if(!strcmp(key,"fps"))fps=(u32)strtoul(val,NULL,10);
        else if(!strcmp(key,"bytes_per_second"))rate=(u32)strtoul(val,NULL,10);
    }
    fclose(f);memset(&target,0,sizeof target);target.sin_family=AF_INET;
    if(port<1||port>65535||inet_pton(AF_INET,ip,&target.sin_addr)!=1)enabled=false;
    target.sin_port=htons((u16)port);
    if(!live_valid_fps(fps)||rate<LIVE_MIN_RATE||rate>LIVE_MAX_RATE)enabled=false;
    return enabled;
}
u32 live_fps(void){return __atomic_load_n(&fps,__ATOMIC_RELAXED);}
u32 live_encoded_frames(unsigned sc){return sc<2?__atomic_load_n(&jpegFrames[sc],__ATOMIC_RELAXED):0;}
static void encode_job(unsigned sc,unsigned kind,unsigned q) {
    u64 begin=svcGetSystemTick();
    if(kind==1)jobChanged[sc]=(u32)live_jpeg_prepare(sc,rawWorking[sc],sc?320:400,240);
    jobSize[sc]=(u32)live_jpeg_render(sc,q,encoded[sc],MAX_JPEG);
    jobUs[sc]+=(u32)((svcGetSystemTick()-begin)*1000000/SYSCLOCK_ARM11);
}
static bool run_pair_job(unsigned kind,unsigned q) {
    jobKind=kind;jobQuality=q;
    __atomic_store_n(&jobDone,0,__ATOMIC_RELEASE);LightEvent_Signal(&events[1]);
    encode_job(0,kind,q);
    while(!__atomic_load_n(&jobDone,__ATOMIC_ACQUIRE)&&!stopped())LightEvent_WaitTimeout(&events[2],1000000);
    return !stopped();
}
static void encoder(void *arg) {
    if((uintptr_t)arg) {
        while(!stopped()) {
            LightEvent_WaitTimeout(&events[1],100000000);
            if(stopped())break;
            if(__atomic_load_n(&jobDone,__ATOMIC_ACQUIRE))continue;
            encode_job(1,jobKind,jobQuality);
            __atomic_store_n(&jobDone,1,__ATOMIC_RELEASE);LightEvent_Signal(&events[2]);
        }
        return;
    }
    u64 next=svcGetSystemTick();
    while(!stopped()) {
        u64 now=svcGetSystemTick();
        if(now<next){svcSleepThread((next-now)*1000000000ull/SYSCLOCK_ARM11);continue;}
        bool ready;u32 stamp=0,source[2]={0,0},jobRate,jobFps,epoch;
        LightLock_Lock(&lock);
        ready=planMask==3&&rawValid[0]&&rawValid[1]&&rawPts[0]==planPts[0]&&rawPts[1]==planPts[1];
        jobRate=rate;jobFps=fps;epoch=configEpoch;
        if(ready) {
            for(unsigned i=0;i<2;i++){memcpy(rawWorking[i],rawPending[i],(i?320:400)*240*2);source[i]=rawPts[i];}
            stamp=planStamp;
        }
        LightLock_Unlock(&lock);
        if(!ready){LightEvent_WaitTimeout(&events[0],1000000);continue;}
        u64 period=SYSCLOCK_ARM11/jobFps;next+=period;if(next<now)next=now+period;
        u32 budget=live_pair_budget(jobRate,jobFps);
        for(unsigned i=0;i<2;i++){sourceReuse[i]+=pairs&&source[i]==lastSource[i];lastSource[i]=source[i];jobUs[i]=0;}
        pairs++;u32 seq=++sequence;unsigned q=quality;
        if(!run_pair_job(1,q))break;
        /* Bounded requantization: reuse DCT, at most 3 entropy passes. */
        for(unsigned retry=0;retry<2;retry++) {
            u32 total=(jobSize[0]?jobSize[0]:MAX_JPEG+1)+(jobSize[1]?jobSize[1]:MAX_JPEG+1);
            if(jobSize[0]&&jobSize[1]&&total<=budget)break;
            retries++;q=retry==1?1:live_lower_quality(q,total,budget);
            if(!run_pair_job(2,q))break;
        }
        if(stopped())break;
        bool fits=jobSize[0]&&jobSize[1]&&jobSize[0]+jobSize[1]<=budget;
        for(unsigned i=0;i<2;i++) {
            attempts[i]++;sumUs[i]+=jobUs[i];changedMcus[i]+=jobChanged[i];
            if(jobUs[i]>maxUs[i])maxUs[i]=jobUs[i];
            __atomic_store_n(&lastEncodeUs[i],jobUs[i],__ATOMIC_RELAXED);
            if(fits){__atomic_add_fetch(&jpegFrames[i],1,__ATOMIC_RELAXED);if(jobSize[i]>maxBytes[i])maxBytes[i]=jobSize[i];}
        }
        quality=q;
        if(!fits){oversize++;spare=0;continue;}
        if(jobSize[0]+jobSize[1]<budget*9/10){if(++spare>=4){quality=quality<83?quality+2:85;spare=0;}}
        else spare=0;
        LightLock_Lock(&lock);
        if(epoch==configEpoch) {
            if(pendingReady)replaced++;
            for(unsigned i=0;i<2;i++){memcpy(pending[i],encoded[i],jobSize[i]);pendingLengths[i]=jobSize[i];}
            pendingSeq=seq;pendingStamp=stamp;pendingEpoch=epoch;pendingAt=svcGetSystemTick();pendingReady=true;
        }
        LightLock_Unlock(&lock);
    }
}
static void control(u64 *due) {
    u64 now=svcGetSystemTick();
    if(now-lastControlTick>=SYSCLOCK_ARM11/100) {
        lastControlTick=now;
        for(unsigned i=0;i<4;i++) {
            u8 msg[64];struct sockaddr_in from;socklen_t size=sizeof from;
            int n=recvfrom(fd,msg,sizeof msg,0,(struct sockaddr*)&from,&size);if(n<0)break;
            if(n<8||get32(msg+4)!=session||from.sin_addr.s_addr!=target.sin_addr.s_addr||from.sin_port!=target.sin_port)continue;
            if(n==28&&!memcmp(msg,"R3FB",4))feedbackCount++;
            if(n==20&&!memcmp(msg,"R6CF",4)) {
                u32 seq=get32(msg+8),hz=get32(msg+12),bps=get32(msg+16);
                if(!live_valid_fps(hz)||bps<LIVE_MIN_RATE||bps>LIVE_MAX_RATE||!seq)continue;
                if(configSequence&&(u32)(seq-configSequence)>=0x80000000u)continue;
                configSequence=seq;
                LightLock_Lock(&lock);
                if(fps!=hz||rate!=bps){__atomic_store_n(&fps,hz,__ATOMIC_RELAXED);rate=bps;configEpoch++;configChanges++;pendingReady=false;}
                LightLock_Unlock(&lock);lastStatusTick=0;
            }
        }
    }
    if(now-lastStatusTick<SYSCLOCK_ARM11)return;
    u8 msg[76];memcpy(msg,"R7ST",4);
    const u32 values[]={session,(u32)((now-started)*1000/SYSCLOCK_ARM11),rate,rate,fps,
        live_encoded_frames(0),live_encoded_frames(1),frames[0],frames[1],errors,expired,feedbackCount,
        (u32)encoderCores[0],(u32)encoderCores[1],
        __atomic_load_n(&lastEncodeUs[0],__ATOMIC_RELAXED),__atomic_load_n(&lastEncodeUs[1],__ATOMIC_RELAXED),
        LIVE_MAX_RATE,LIVE_FPS_MASK};
    for(unsigned i=0;i<18;i++)put32(msg+4+4*i,values[i]);
    if(*due>now)svcSleepThread((*due-now)*1000000000ull/SYSCLOCK_ARM11);
    u64 begin=svcGetSystemTick();sendto(fd,msg,sizeof msg,0,(struct sockaddr*)&target,sizeof target);
    *due=live_packet_due(*due,begin,sizeof msg+28,rate,SYSCLOCK_ARM11);lastStatusTick=begin;
}
static bool send_packet(u64 *due,u64 deadline,const char *magic,u32 seq,u32 stamp,
                        u32 sc,u32 total,u32 offset,const u8 *data,u32 len) {
    u64 now=svcGetSystemTick();
    if(*due>now)svcSleepThread((*due-now)*1000000000ull/SYSCLOCK_ARM11);
    if(stopped()||svcGetSystemTick()>deadline)return false;
    u8 packet[1200];memcpy(packet,magic,4);put32(packet+4,session);put32(packet+8,seq);put32(packet+12,stamp);
    put32(packet+16,sc);put32(packet+20,total);put32(packet+24,offset);put32(packet+28,fps);
    memcpy(packet+32,data,len);u64 begin=svcGetSystemTick();
    int sent=sendto(fd,packet,len+32,0,(struct sockaddr*)&target,sizeof target);
    u32 us=(u32)((svcGetSystemTick()-begin)*1000000/SYSCLOCK_ARM11);
    sendCalls++;sendSumUs+=us;if(us>sendMaxUs)sendMaxUs=us;
    *due=live_packet_due(*due,begin,len+60,rate,SYSCLOCK_ARM11);
    if(sent!=(int)(len+32)){lastErrno=errno;errors++;return false;}return true;
}
static void sender(void *unused) {
    (void)unused;u64 due=svcGetSystemTick();
    while(!stopped()) {
        control(&due);u32 sizes[2]={0,0},seq=0,stamp=0;u64 queued=0;bool ready;
        LightLock_Lock(&lock);ready=pendingReady&&pendingEpoch==configEpoch;
        if(ready){for(unsigned i=0;i<2;i++){sizes[i]=pendingLengths[i];memcpy(sending[i],pending[i],sizes[i]);}
            seq=pendingSeq;stamp=pendingStamp;queued=pendingAt;pendingReady=false;}
        LightLock_Unlock(&lock);
        if(!ready){svcSleepThread(500000);continue;}
        u64 begin=svcGetSystemTick(),deadline=begin+SYSCLOCK_ARM11/fps;
        if(begin-queued>SYSCLOCK_ARM11/fps*2){expired++;continue;}
        u8 parity[2][LIVE_PARITY][LIVE_CHUNK]={0};bool ok=true;
        for(u32 off=0;ok&&(off<sizes[0]||off<sizes[1]);off+=LIVE_CHUNK)for(unsigned sc=0;sc<2&&ok;sc++) {
            if(off>=sizes[sc])continue;
            u32 len=sizes[sc]-off>LIVE_CHUNK?LIVE_CHUNK:sizes[sc]-off;
            u8 *stripe=parity[sc][off/LIVE_CHUNK%LIVE_PARITY];
            for(u32 j=0;j<len;j++)stripe[j]^=sending[sc][off+j];
            ok=send_packet(&due,deadline,"R3P2",seq,stamp,sc,sizes[sc],off,sending[sc]+off,len);
        }
        for(unsigned stripe=0;stripe<LIVE_PARITY&&ok;stripe++)for(unsigned sc=0;sc<2&&ok;sc++)
            ok=send_packet(&due,deadline,"R3F2",seq,stamp,sc,sizes[sc],stripe,parity[sc][stripe],LIVE_CHUNK);
        if(ok){frames[0]++;frames[1]++;}else expired++;
    }
}
Result live_start(void) {
    if(worker||encoders[0]||encoders[1])return -1;
    LightLock_Init(&lock);for(unsigned i=0;i<3;i++)LightEvent_Init(&events[i],RESET_ONESHOT);
    started=svcGetSystemTick();stopping=false;jobDone=1;pendingReady=false;planMask=0;
    memset(rawValid,0,sizeof rawValid);memset(attempts,0,sizeof attempts);memset(jpegFrames,0,sizeof jpegFrames);
    memset(maxUs,0,sizeof maxUs);memset(maxBytes,0,sizeof maxBytes);memset(sumUs,0,sizeof sumUs);
    memset(convertCount,0,sizeof convertCount);memset(convertMaxUs,0,sizeof convertMaxUs);memset(convertSumUs,0,sizeof convertSumUs);
    memset(changedMcus,0,sizeof changedMcus);memset(sourceReuse,0,sizeof sourceReuse);memset(lastSource,0,sizeof lastSource);
    memset(frames,0,sizeof frames);memset(lastEncodeUs,0,sizeof lastEncodeUs);
    sequence=replaced=errors=expired=oversize=retries=pairs=sendCalls=sendMaxUs=feedbackCount=0;
    configEpoch=configSequence=configChanges=0;sendSumUs=0;lastErrno=0;quality=60;spare=0;
    session=(u32)started;lastStatusTick=lastControlTick=started;
    for(unsigned i=0;i<2;i++)live_jpeg_reset(i);
    Result rc=socInit(socStorage,sizeof socStorage);if(R_FAILED(rc))return rc;
    socReady=true;fd=socket(AF_INET,SOCK_DGRAM,0);
    if(fd<0){live_stop();return -3;}if(fcntl(fd,F_SETFL,O_NONBLOCK)<0){live_stop();return -4;}
    for(int i=1;i>=0;i--) {
        encoderCores[i]=i+2;
        encoders[i]=threadCreate(encoder,(void*)(uintptr_t)i,8192,0x3E,encoderCores[i],false);
        if(!encoders[i]){encoderCores[i]=1;encoders[i]=threadCreate(encoder,(void*)(uintptr_t)i,8192,0x3E,1,false);}
        if(!encoders[i]){live_stop();return -6;}
    }
    worker=threadCreate(sender,NULL,16384,0x3E,1,false);if(!worker){live_stop();return -5;}return 0;
}
void live_stop(void) {
    __atomic_store_n(&stopping,true,__ATOMIC_RELEASE);
    for(unsigned i=0;i<3;i++)LightEvent_Signal(&events[i]);
    for(unsigned i=0;i<2;i++)if(encoders[i]){threadJoin(encoders[i],U64_MAX);threadFree(encoders[i]);encoders[i]=NULL;}
    if(worker){threadJoin(worker,U64_MAX);threadFree(worker);worker=NULL;}
    if(fd>=0){close(fd);fd=-1;}if(socReady){socExit();socReady=false;}
    FILE *f=fopen("sdmc:/3ds/recorder/live-stats.txt","w");if(!f)return;
    fprintf(f,"version=live-r7\nsent_top=%lu\nsent_bottom=%lu\nreplaced=%lu\nsend_errors=%lu\nrate=%lu\nfps=%lu\n",
        frames[0],frames[1],replaced,errors,rate,fps);
    fprintf(f,"duration_ms=%llu\nexpired_pairs=%lu\nlast_send_errno=%d\nadaptive=0\npair_jpeg_budget=%lu\n",
        (svcGetSystemTick()-started)*1000/SYSCLOCK_ARM11,expired,lastErrno,(u32)live_pair_budget(rate,fps));
    fprintf(f,"pairs_attempted=%lu\npairs_oversize=%lu\nrequantize_passes=%lu\nquality=%u\nfec_stripes=%u\nconfig_changes=%lu\n",
        pairs,oversize,retries,quality,LIVE_PARITY,configChanges);
    fprintf(f,"send_calls=%lu\nsend_mean_us=%llu\nsend_max_us=%lu\nfeedback_count=%lu\n",
        sendCalls,sendCalls?sendSumUs/sendCalls:0,sendMaxUs,feedbackCount);
    for(unsigned i=0;i<2;i++)fprintf(f,
        "screen%u_attempts=%lu\nscreen%u_jpeg=%lu\nscreen%u_encode_mean_us=%llu\nscreen%u_encode_max_us=%lu\n"
        "screen%u_max_bytes=%lu\nscreen%u_encoder_core=%ld\nscreen%u_changed_mcus=%llu\nscreen%u_source_reused=%lu\n"
        "screen%u_convert_mean_us=%llu\nscreen%u_convert_max_us=%lu\n",
        i,attempts[i],i,jpegFrames[i],i,attempts[i]?sumUs[i]/attempts[i]:0,i,maxUs[i],i,maxBytes[i],i,encoderCores[i],
        i,changedMcus[i],i,sourceReuse[i],i,convertCount[i]?convertSumUs[i]/convertCount[i]:0,i,convertMaxUs[i]);
    fclose(f);
}
bool live_submit(int sc,const u8 *frame,u32 fmt,u32 stride,u32 pts,bool wide) {
    if(sc<0||sc>1||!worker||stopped()||wide)return false;
    u64 begin=svcGetSystemTick();u32 w=sc?320:400;
    if(!fb_to_rgb565(rgb565,frame,fmt,w,240,stride,1))return false;
    LightLock_Lock(&lock);memcpy(rawPending[sc],rgb565,w*240*2);rawPts[sc]=pts;rawValid[sc]=true;LightLock_Unlock(&lock);
    LightEvent_Signal(&events[0]);u32 us=(u32)((svcGetSystemTick()-begin)*1000000/SYSCLOCK_ARM11);
    convertCount[sc]++;convertSumUs[sc]+=us;if(us>convertMaxUs[sc])convertMaxUs[sc]=us;return true;
}
void live_schedule(u32 stamp,u32 top,u32 bottom,u32 mask) {
    if(!worker||stopped())return;
    LightLock_Lock(&lock);planStamp=stamp;planPts[0]=top;planPts[1]=bottom;planMask=mask;LightLock_Unlock(&lock);
}
