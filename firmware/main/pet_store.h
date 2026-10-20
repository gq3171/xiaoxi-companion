#pragma once
#include "cJSON.h"
#include <stdbool.h>

int pet_store_start(void);
int pet_store_load_wifi(char *ssid, int ssid_len, char *password, int password_len);
void pet_store_save_wifi(const char *ssid, const char *password);
/* Apply a private build's requested network once; later screen changes persist. */
void pet_store_seed_wifi(void);
int pet_store_has_soul(void);
bool pet_store_identity_needs_review(void);
cJSON *pet_store_identity_legacy(void);
cJSON *pet_store_identity_export(void);
int pet_store_write_identity(const cJSON *identity);
void pet_store_creature(char *out, int capacity);
int pet_store_system(char *buf, int len);
void pet_store_remember(const char *quote);
void pet_store_recent(char *buf, int len);

void pet_store_name(char *out,int capacity);
