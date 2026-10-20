#pragma once
/* Provider response -> bounded source data. NULL on errors/empty results. */
char *pet_search_sources(const char *response);
const char *pet_search_rules(void);
