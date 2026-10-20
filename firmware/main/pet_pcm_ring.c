#include "pet_pcm_ring.h"
void pet_pcm_ring_init(pet_pcm_ring_t*r,int16_t*data,unsigned capacity)
{r->data=data;r->capacity=capacity;atomic_store(&r->read,0);atomic_store(&r->write,0);}
unsigned pet_pcm_ring_used(const pet_pcm_ring_t*r)
{unsigned w=atomic_load(&r->write),v=atomic_load(&r->read);return w-v;}
size_t pet_pcm_ring_push(pet_pcm_ring_t*r,const int16_t*data,size_t samples)
{
 unsigned w=atomic_load(&r->write),v=atomic_load(&r->read),free=r->capacity-(w-v);
 if(samples>free)samples=free;
 for(size_t i=0;i<samples;i++)r->data[(w+i)%r->capacity]=data[i];
 atomic_store(&r->write,w+samples);return samples;
}
size_t pet_pcm_ring_pop(pet_pcm_ring_t*r,int16_t*data,size_t samples)
{
 unsigned v=atomic_load(&r->read),w=atomic_load(&r->write),used=w-v;
 if(samples>used)samples=used;
 for(size_t i=0;i<samples;i++)data[i]=r->data[(v+i)%r->capacity];
 atomic_store(&r->read,v+samples);return samples;
}
