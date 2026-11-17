#include "live_pacing.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    /* 1228 bytes at 800 kB/s: one packet every 1535 us. A 600 us IPC
     * call must consume that interval, not lower throughput to 575 kB/s. */
    uint64_t now=0,due=0;
    for(unsigned i=0;i<1000;i++) {
        if(now<due)now=due;
        due=live_packet_due(due,now,1228,800000,1000000);
        now+=600;
    }
    assert(due==1535000);
    assert(1228000ull*1000000/due==800000);
    /* Idle periods and scheduling delays don't authorize bursts. */
    now=due+100000;
    assert(live_packet_due(due,now,1228,800000,1000000)==now+1535);
    /* Blocking longer than one packet interval also incurs no extra penalty. */
    now=due+2500;
    assert(live_packet_due(due,now,1228,800000,1000000)==now+1535);
    /* Rounding is upward, including the smallest tail packet. */
    assert(live_packet_due(0,0,61,700000,1000000)==88);
    puts("packet pacing: byte cap, IPC time, idle and rounding OK");
    return 0;
}
