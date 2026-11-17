#ifndef LIVE_PAIR_H
#define LIVE_PAIR_H
#include <stdint.h>
#define LIVE_CHUNK 1168u
#define LIVE_PARITY 2u
#define LIVE_MIN_RATE 400000u
#define LIVE_MAX_RATE 2000000u
#define LIVE_FPS_MASK ((1u<<15)|(1u<<20)|(1u<<24)|(1u<<30))
static inline int live_valid_fps(uint32_t fps) { return fps==15||fps==20||fps==24||fps==30; }
/* Two striped XOR packets per screen. Count all headers and parity in the
 * fixed budget. 4% headroom covers status and scheduling, never burst credit. */
static inline uint32_t live_screen_wire(uint32_t bytes) {
    return bytes+60*((bytes+LIVE_CHUNK-1)/LIVE_CHUNK)+LIVE_PARITY*(LIVE_CHUNK+60);
}
static inline uint32_t live_pair_budget(uint32_t rate,uint32_t fps) {
    uint32_t available=rate/fps*96/100-2*LIVE_PARITY*(LIVE_CHUNK+60);
    return (available-120)*LIVE_CHUNK/(LIVE_CHUNK+60);
}
static inline unsigned live_lower_quality(unsigned quality,uint32_t size,uint32_t budget) {
    unsigned scale=quality<50?5000/quality:200-2*quality;
    uint32_t next=(uint32_t)((uint64_t)scale*size*110/(budget*100));
    unsigned q=next>100?5000/(next?next:1):100-next/2;
    if(q>=quality)q=quality>4?quality-4:1;
    return q<1?1:q;
}
#endif
