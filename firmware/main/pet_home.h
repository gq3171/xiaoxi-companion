#pragma once
#define PET_BED_PILLOW_X 130
#define PET_BED_PILLOW_Y 174
#define PET_BED_HEAD_X 64
#define PET_BED_HEAD_Y 88
#define PET_BED_SLEEP_SCALE 128
#define PET_BED_COVER_Y 198
#define PET_BED_COVER_H 70
#define PET_BED_COVER_W 168
#include <stdbool.h>
#include <stddef.h>

typedef enum { PET_PLACE_FLOOR, PET_PLACE_BED, PET_PLACE_WASH, PET_PLACE_WORK, PET_PLACE_WINDOW, PET_PLACE_COUNT } pet_place_t;
typedef enum { PET_HOME_NONE, PET_HOME_ROAM, PET_HOME_REST, PET_HOME_WAKE, PET_HOME_WASH, PET_HOME_WORK, PET_HOME_WINDOW, PET_HOME_READ } pet_home_action_t;
typedef enum {
    PET_HOME_IDLE, PET_HOME_WALKING, PET_HOME_GETTING_IN_BED, PET_HOME_SLEEPING,
    PET_HOME_WAKING, PET_HOME_WASHING, PET_HOME_WAIT_COMPUTER, PET_HOME_WORKING, PET_HOME_LOOKING, PET_HOME_SITTING, PET_HOME_STANDING, PET_HOME_READING
} pet_home_activity_t;
typedef enum { PET_COMPUTER_DISCONNECTED, PET_COMPUTER_READY, PET_COMPUTER_RUNNING, PET_COMPUTER_ERROR, PET_COMPUTER_UNCHECKED } pet_computer_state_t;
typedef struct {
    pet_place_t place;
    const char *name;
    int approach_x, approach_y, use_x, use_y;
    int x, y, w, h, front_y; /* Furniture hitbox and depth plane, in screen pixels. */
    int mask_x, mask_y, mask_w, mask_h; /* Exact background crop, no extra bitmap. */
} pet_home_spot_t;

extern const pet_home_spot_t pet_home_spots[PET_PLACE_COUNT];
bool pet_home_request(pet_home_action_t action);
bool pet_home_request_text(const char *action);
pet_home_action_t pet_home_take_request(void);
pet_computer_state_t pet_home_computer_state(void);
/* Future real-computer adapter must call this only from actual connection/task events. */
void pet_home_computer_event(pet_computer_state_t state);
void pet_home_report(pet_home_activity_t activity, pet_place_t place, pet_place_t destination, int x, int y);
/* Completed virtual-life transitions only; not a record of physical-world work. */
void pet_home_complete(pet_home_activity_t activity);
/* Packed sequence+actual completion, for the worker to persist outside LVGL. */
unsigned pet_home_completion(void);
typedef struct { pet_home_activity_t activity; pet_place_t place,destination; } pet_home_status_t;
pet_home_status_t pet_home_status(void);
unsigned pet_home_request_serial(void);
pet_home_action_t pet_home_action(const char *name);
const char *pet_home_action_name(pet_home_action_t action);
void pet_home_description(char *out, size_t capacity);
int pet_home_scale(int floor_y);
void pet_home_floor_clamp(int *x, int *y);
bool pet_home_floor_contains(int x, int y);
