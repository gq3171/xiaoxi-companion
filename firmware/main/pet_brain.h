#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "cJSON.h"
bool pet_brain_enabled(void);
int pet_brain_start(void);
bool pet_brain_ensure(void);
bool pet_brain_reconcile(void);
cJSON *pet_brain_envelope(void);
/* Operation is copied into a CRC-protected outbox before network submission. */
int pet_brain_memory(const cJSON *operation);
/* Durable receipts are queued without a network round trip on the speech path. */
int pet_brain_receipt(const char *trace,const char *stage,int source_id);
void pet_brain_tick(uint32_t now);
