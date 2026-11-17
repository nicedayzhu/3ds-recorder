#include <assert.h>
#include <stdio.h>
#include "live_pair.h"
int main(void) {
    for(unsigned rate=620000;rate<=1000000;rate+=10000)for(unsigned fps=24;fps<=30;fps+=6) {
        unsigned budget=live_pair_budget(rate,fps);
        for(unsigned top=1024;top<budget-1024;top++) {
            unsigned bottom=budget-top;
            assert((uint64_t)(live_screen_wire(top)+live_screen_wire(bottom))*fps+96<=rate);
        }
        for(unsigned q=2;q<=95;q++)assert(live_lower_quality(q,budget+1,budget)<q);
    }
    puts("pair budget: all splits, parity, headers and status fit fixed rate");return 0;
}
