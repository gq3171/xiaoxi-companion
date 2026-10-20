#pragma once
#include <assert.h>
#define ESP_OK 0
#define ESP_ERROR_CHECK(x) assert((x)==0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
