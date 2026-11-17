#ifndef REC_LIVE_STREAM_H
#define REC_LIVE_STREAM_H
#include <3ds.h>
bool live_requested(void);
u32 live_fps(void);
u32 live_encoded_frames(unsigned screen);
Result live_start(void);
void live_stop(void);
bool live_submit(int screen,const u8 *frame,u32 format,u32 stride,u32 timeUs,bool wide);
#endif
