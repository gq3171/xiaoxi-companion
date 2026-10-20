set(owner_sources "pet_owner.c")
set(media_sources "")
set(panel_sources "character/pet_character_assets.c" "fonts/pet_font_cn_16.c")
if(CONFIG_DESKPET_PANEL_CACHE)
    set(panel_sources "panel/pet_panel_art.c" "panel/pet_panel_font.c" "pet_panel.c" "pet_panel_cache.c")
endif()
if(CONFIG_DESKPET_MEDIA)
    set(media_sources "pet_media.c")
endif()
if(CONFIG_DESKPET_LOCAL_OWNER)
    set(owner_sources "pet_owner_local.c" "pet_owner_embedding.cpp")
endif()

idf_component_register(
    SRCS "main.c" "pet_face.c" "pet_scene.c" "pet_home.c" "pet_scene_wire.c" "pet_home_sync.c" "pet_asset_codec.c" ${panel_sources} "pet_display.c" "pet_audio.c" "pet_capture.c" "pet_cloud.c" "pet_controls.c"
         "pet_store.c" "pet_setup.c" "pet_voice.c" "pet_tts.c" "pet_search.c" "pet_screen.c" "pet_life.c" "pet_computer.c" "pet_brain.c" "pet_memory.c" "pet_input.c" "pet_policy.c" "pet_turn.c"
         "pet_util.c" "pet_stream.c" "pet_pcm_ring.c" "pet_latency.c" "pet_motion.c" "pet_orientation.c" "pet_wake_gate.c" "pet_wake.c" "pet_wake_level.c" "pet_wake_name.c" "pet_birth.c" "pet_secrets.c" "pet_owner_session.c" ${owner_sources} ${media_sources} "pet_hardware.c" "pet_runtime.c" "pet_speech.c" "pet_bargein.c" "fonts/pet_font_owner_28.c" "fonts/pet_font_symbols_16.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash esp_wifi esp_event esp_netif esp_http_client esp_http_server esp-tls json spiffs esp_driver_gpio esp_driver_i2c esp_timer lwip mbedtls espressif__esp_new_jpeg
)
if(CONFIG_DESKPET_WAKE)
    target_add_binary_data(${COMPONENT_LIB} "../assets/voice/wake_ack.pcm" BINARY)
endif()
if(CONFIG_DESKPET_COMPUTER_CA_FILE)
    target_add_binary_data(${COMPONENT_LIB} "${CMAKE_CURRENT_LIST_DIR}/../${CONFIG_DESKPET_COMPUTER_CA_FILE}" TEXT RENAME_TO pet_computer_ca)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE PET_COMPUTER_CUSTOM_CA=1)
endif()
if(CONFIG_DESKPET_LOCAL_OWNER)
    idf_component_get_property(owner_espdl_dir espressif__esp-dl COMPONENT_DIR)
    include(${owner_espdl_dir}/cmake/compile_register.cmake)
    esp_dl_compile_add_yml(${CMAKE_CURRENT_LIST_DIR}/../models/owner.compile_req.yml)
    set(cmake_dir ${owner_espdl_dir}/fbs_loader/cmake)
    include(${cmake_dir}/utilities.cmake)
    target_add_aligned_binary_data(${COMPONENT_LIB} "../models/pet_owner_sv_s3.espdl" BINARY)
endif()

idf_component_get_property(LVGL_LIB lvgl__lvgl COMPONENT_LIB)
if(LVGL_LIB)
    target_compile_options(${LVGL_LIB} PRIVATE -DLV_LVGL_H_INCLUDE_SIMPLE)
endif()
