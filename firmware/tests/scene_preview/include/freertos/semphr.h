#pragma once
#include <stdint.h>
typedef void *SemaphoreHandle_t;
void *xSemaphoreCreateBinary(void);
int xSemaphoreTake(void*,uint32_t);
int xSemaphoreGive(void*);
