#include "firmware_config.h"

int main(void) {
    struct firmware_config config;
    firmware_config_set_defaults(&config);
    if (!firmware_config_validate(&config)) {
        return 1;
    }
    config.sample_interval_ms = UINT32_C(0);
    if (firmware_config_validate(&config)) {
        return 2;
    }
    config.sample_interval_ms = UINT32_C(100);
    config.mode = (enum firmware_config_mode)99;
    if (firmware_config_validate(&config)) {
        return 3;
    }
    firmware_config_set_defaults(&config);
    config.label[0] = '\n';
    if (firmware_config_validate(&config)) {
        return 4;
    }
    return 0;
}
