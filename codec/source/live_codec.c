#include "live_codec.h"
#include <string.h>

static uint16_t rd(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static void wr(uint8_t *p, unsigned v) { p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); }
static unsigned r(uint16_t p) { return (p>>11)*255/31; }
static unsigned g(uint16_t p) { return ((p>>5)&63)*255/63; }
static unsigned b(uint16_t p) { return (p&31)*255/31; }
static uint16_t pack(unsigned rr,unsigned gg,unsigned bb) {
    return (uint16_t)(((rr>>3)<<11)|((gg>>2)<<5)|(bb>>3));
}
static unsigned dist(uint16_t a,uint16_t c) {
    int dr=(int)r(a)-(int)r(c), dg=(int)g(a)-(int)g(c), db=(int)b(a)-(int)b(c);
    return (unsigned)(dr*dr+dg*dg+db*db);
}
/* Two centroid colors partitioned by luma; one selector bit per pixel. */
static void btc(const uint16_t *p, unsigned n, uint8_t *out) {
    unsigned mean=0, sums[2][3]={{0}}, count[2]={0};
    for(unsigned i=0;i<n;i++) mean+=r(p[i])+2*g(p[i])+b(p[i]);
    mean/=n;
    memset(out,0,4+n/8);
    for(unsigned i=0;i<n;i++) {
        unsigned k=(r(p[i])+2*g(p[i])+b(p[i])>mean);
        sums[k][0]+=r(p[i]); sums[k][1]+=g(p[i]); sums[k][2]+=b(p[i]); count[k]++;
        out[4+i/8]|=(uint8_t)(k<<(i%8));
    }
    for(unsigned k=0;k<2;k++) {
        unsigned c=count[k]?count[k]:1;
        wr(out+2*k,pack(sums[k][0]/c,sums[k][1]/c,sums[k][2]/c));
    }
}
static uint16_t pick(const uint8_t *p,unsigned i) {
    return rd(p+2*((p[4+i/8]>>(i%8))&1));
}
static void sift(LiveScratch *s,unsigned n,unsigned root) {
    for(;;) {
        unsigned child=root*2+1;
        if(child>=n) return;
        if(child+1<n && s->gain[s->order[child+1]]>s->gain[s->order[child]]) child++;
        if(s->gain[s->order[root]]>=s->gain[s->order[child]]) return;
        uint16_t t=s->order[root];s->order[root]=s->order[child];s->order[child]=t;root=child;
    }
}
size_t live_encode(LiveScratch *s,const uint16_t *src,unsigned w,unsigned h,
                   size_t budget,uint8_t *out,size_t cap) {
    if(!s||!src||!out||h!=240||(w!=400&&w!=320)) return 0;
    unsigned tiles=w*h/64;
    size_t used=12+tiles*7;
    if(budget>cap) budget=cap;
    if(budget<used) return 0;
    for(unsigned t=0;t<tiles;t++) {
        unsigned tx=(t%(w/8))*8,ty=(t/(w/8))*8;
        uint16_t pix[64], half[16];
        for(unsigned y=0;y<8;y++) for(unsigned x=0;x<8;x++)
            pix[y*8+x]=src[(tx+x)*h+(h-1-(ty+y))];
        for(unsigned y=0;y<4;y++) for(unsigned x=0;x<4;x++) {
            unsigned rr=0,gg=0,bb=0;
            for(unsigned dy=0;dy<2;dy++) for(unsigned dx=0;dx<2;dx++) {
                uint16_t p=pix[(2*y+dy)*8+2*x+dx];rr+=r(p);gg+=g(p);bb+=b(p);
            }
            half[y*4+x]=pack(rr/4,gg/4,bb/4);
        }
        s->base[t][0]=0;btc(half,16,s->base[t]+1);
        uint8_t full[13],fine[25];full[0]=1;fine[0]=2;
        btc(pix,64,full+1);
        for(unsigned q=0;q<4;q++) {
            uint16_t block[16];
            for(unsigned y=0;y<4;y++) for(unsigned x=0;x<4;x++)
                block[y*4+x]=pix[(y+(q/2)*4)*8+x+(q%2)*4];
            btc(block,16,fine+1+q*6);
        }
        unsigned e0=0,e1=0,e2=0;
        for(unsigned y=0;y<8;y++) for(unsigned x=0;x<8;x++) {
            uint16_t p=pix[y*8+x];
            e0+=dist(p,pick(s->base[t]+1,(y/2)*4+x/2));
            e1+=dist(p,pick(full+1,y*8+x));
            e2+=dist(p,pick(fine+1+(y/4*2+x/4)*6,(y%4)*4+x%4));
        }
        unsigned gain1=e0>e1?(e0-e1)/6:0, gain2=e0>e2?(e0-e2)/18:0;
        memcpy(s->data[t],gain1>=gain2?full:fine,gain1>=gain2?13:25);
        s->gain[t]=gain1>=gain2?gain1:gain2;s->order[t]=(uint16_t)t;
    }
    for(unsigned i=tiles/2;i>0;i--) sift(s,tiles,i-1);
    /* A max heap ranks distortion reduction per additional byte. */
    for(unsigned n=tiles;n>0;n--) {
        unsigned t=s->order[0],extra=s->data[t][0]==1?6:18;
        if(!s->gain[t]||used+extra>budget) s->data[t][0]=0;
        else used+=extra;
        s->order[0]=s->order[n-1];sift(s,n-1,0);
    }
    memcpy(out,"LTC1",4);wr(out+4,w);wr(out+6,h);wr(out+8,tiles);wr(out+10,0);
    size_t at=12;
    for(unsigned t=0;t<tiles;t++) {
        const uint8_t *p=s->data[t][0]?s->data[t]:s->base[t];
        unsigned len=p[0]==0?7:p[0]==1?13:25;
        memcpy(out+at,p,len);at+=len;
    }
    return at;
}
int live_decode(const uint8_t *src,size_t size,uint8_t *rgb,size_t cap) {
    if(!src||!rgb||size<12||memcmp(src,"LTC1",4)) return -1;
    unsigned w=rd(src+4),h=rd(src+6),tiles=rd(src+8);
    if((w!=400&&w!=320)||h!=240||tiles!=w*h/64||rd(src+10)||cap<(size_t)w*h*3) return -1;
    size_t at=12;
    for(unsigned t=0;t<tiles;t++) {
        if(at>=size||src[at]>2) return -1;
        at+=src[at]==0?7:src[at]==1?13:25;
        if(at>size) return -1;
    }
    if(at!=size) return -1;
    at=12;
    for(unsigned t=0;t<tiles;t++) {
        unsigned mode=src[at],tx=t%(w/8)*8,ty=t/(w/8)*8;
        const uint8_t *p=src+at+1;
        for(unsigned y=0;y<8;y++) for(unsigned x=0;x<8;x++) {
            uint16_t c=mode==0?pick(p,y/2*4+x/2):mode==1?pick(p,y*8+x):
                       pick(p+(y/4*2+x/4)*6,y%4*4+x%4);
            uint8_t *d=rgb+((ty+y)*w+tx+x)*3;d[0]=(uint8_t)r(c);d[1]=(uint8_t)g(c);d[2]=(uint8_t)b(c);
        }
        at+=mode==0?7:mode==1?13:25;
    }
    return (int)(w*h*3);
}
