#ifndef LIVE_RATE_H
#define LIVE_RATE_H
#include <stdint.h>
typedef struct { uint32_t current,ceiling,stable; } LiveRate;
static inline void live_rate_init(LiveRate *c,uint32_t ceiling) {
    c->ceiling=ceiling;c->current=ceiling<800000?ceiling:800000;c->stable=0;
}
/* One observation per second. Fast reductions, slow recovery; all arithmetic
 * uses interval deltas. It controls encoder bytes, not capture FPS. */
static inline uint32_t live_rate_update(LiveRate *c,uint32_t sent_packets,uint32_t received_packets,
                                       uint32_t completed,uint32_t incomplete,uint32_t lag_ms) {
    uint64_t observed=(uint64_t)completed+incomplete;
    if(sent_packets<30)return c->current;
    int packet_loss=(uint64_t)received_packets*100<(uint64_t)sent_packets*85;
    if(observed<5 && !packet_loss)return c->current;
    int loss=packet_loss || (uint64_t)incomplete*100>observed*8;
    if(loss || lag_ms>70) {
        uint32_t next=c->current*(loss?85u:90u)/100;
        c->current=next<400000?400000:next;c->stable=0;
    } else if((uint64_t)incomplete*100<=observed*2 && lag_ms<30) {
        if(++c->stable>=3) {
            uint32_t next=c->current+c->current/40;
            c->current=next>c->ceiling?c->ceiling:next;c->stable=0;
        }
    } else c->stable=0;
    return c->current;
}
#endif
