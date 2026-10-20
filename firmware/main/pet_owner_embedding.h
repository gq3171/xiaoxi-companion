#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
#define PET_OWNER_EMBED_DIM 512
/* Version binds a saved template to its exact model and frontend. */
#define PET_OWNER_LOCAL_MODEL_ID "sv3s-s3-height16-v1"
bool pet_owner_embedding(const int16_t *pcm, int samples, float out[PET_OWNER_EMBED_DIM]);
bool pet_owner_embedding_ready(void);
bool pet_owner_embedding_prepare(void);
#ifdef __cplusplus
}
#endif
