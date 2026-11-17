#ifndef LIVE_PACING_H
#define LIVE_PACING_H
#include <stdint.h>
/* Charge from submission start. Time spent inside sendto is already part of
 * this interval, not an additional sleep. Late wakes never accrue burst credit.
 * Caller validates rate>0; wire_bytes includes the IPv4 and UDP headers. */
static inline uint64_t live_packet_due(uint64_t previous_due,uint64_t start,
                                       uint32_t wire_bytes,uint32_t rate,uint64_t ticks_per_second) {
    uint64_t base=start>previous_due?start:previous_due;
    return base+((uint64_t)wire_bytes*ticks_per_second+rate-1)/rate;
}
#endif
