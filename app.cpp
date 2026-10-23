#include "app.h"
#include <stdio.h>
#include <spike/hub/imu.h>
#include <libcpp/spike/Motor.h>
#include <libcpp/spike/Clock.h>
#include <libcpp/spike/ForceSensor.h>
#include <spike/pup/colorsensor.h>
#include <spike/pup/ultrasonicsensor.h>
#include <spike/hub/display.h>
#include <spike/hub/button.h>
#include <cstdint>
#include <cmath>

#include <serial/serial.h>
#include <serial/newlib.h>

#define MAX_DATA_COUNT 500

int r_array[MAX_DATA_COUNT];
int g_data_array[MAX_DATA_COUNT];
int b_array[MAX_DATA_COUNT];
int data_counter = 0;

// RGBのいずれかがこの値以上変化したら保存
const int COLOR_THRESHOLD = 5;

using namespace spikeapi;

bool blue(int r, int g, int b) {
    return (r > 3 && r < 12 && g > 13 && g < 23 && b > 25 && b < 40);
}

bool red(int r, int g, int b) {
    return (r > 25 && r < 30 && g > 5 && g < 10 && b > 8 && b < 12);
}

bool yellow(int r, int g, int b) {
    return (r > 35 && r < 40 && g > 27 && g < 34 && b > 15 && b < 20);
}

void main_task(intptr_t unused) {
    Clock clock;

    Motor armMotor(
        EPort::PORT_D,
        Motor::EDirection::COUNTERCLOCKWISE,
        true
    );

    Motor leftWheel(
        EPort::PORT_B,
        Motor::EDirection::COUNTERCLOCKWISE,
        true
    );

    Motor rightWheel(
        EPort::PORT_A,
        Motor::EDirection::CLOCKWISE,
        true
    );

    pup_device_t *ultrasonic;
    ultrasonic = pup_ultrasonic_sensor_get_device(PBIO_PORT_ID_F);

    pup_device_t *colorC;
    colorC = pup_color_sensor_get_device(PBIO_PORT_ID_E);

    pup_color_rgb_t rgb;

    int r = 0, g = 0, b = 0;
    int speed = 110;
    int aowokosu = 0;
    float Kp = 0.5;
    int scene = 0;
    int hosei = 60;
    int kosuhanntei = 2;
    int kaisuub = 0;
    int32_t distance = 0;

    bool cooldownActive = false;
    int cooldownCounter = 0;
    const int COOLDOWN_LOOPS = 300;

    hub_button_t button;

    // ------------------------------------------------------------
    // ★追加：保存件数の定期表示に関する設定
    // ------------------------------------------------------------

    // ループ回数を数えるカウンター
    int display_timer = 0;

    // ループ末尾の10ms待機を基準に、約10秒ごとに表示
    const int DISPLAY_INTERVAL_LOOPS = 1000;

    // FULL表示後に定期表示で上書きしないためのフラグ
    bool full_reached = false;

    hub_imu_init();

    while (!hub_imu_is_ready()) {
        clock.sleep(10);
    }

    // ------------------------------------------------------------
    // 1. RGBデータを読み取り、変化があった場合だけ保存
    // ------------------------------------------------------------
    while (1) {

        leftWheel.setPower(0);
        rightWheel.setPower(0);

        // カラーセンサーからRGB値を取得
        rgb = pup_color_sensor_rgb(colorC);

        r = (rgb.r * 255) / 1023;
        g = (rgb.g * 255) / 1023;
        b = (rgb.b * 255) / 1023;

        bool has_changed = false;

        if (data_counter == 0) {

            // 初回のデータは必ず保存する
            has_changed = true;

        } else {

            // 直前に保存したデータと比較
            int prev_idx = data_counter - 1;

            if ((std::abs(r - r_array[prev_idx]) >= COLOR_THRESHOLD) ||
                (std::abs(g - g_data_array[prev_idx]) >= COLOR_THRESHOLD) ||
                (std::abs(b - b_array[prev_idx]) >= COLOR_THRESHOLD)) {

                has_changed = true;
            }
        }

        // 空きがあり、RGB値に十分な変化があった場合だけ保存
        if (data_counter < MAX_DATA_COUNT && has_changed) {

            r_array[data_counter] = r;
            g_data_array[data_counter] = g;
            b_array[data_counter] = b;

            data_counter++;

            // 500件に到達した瞬間にFULLを表示
            if (data_counter == MAX_DATA_COUNT) {

                hub_display_text_scroll("FULL", 100);

                full_reached = true;
            }
        }

        // ------------------------------------------------------------
        // 右ボタンの判定
        // ------------------------------------------------------------
        hub_button_is_pressed(&button);

        if (button & HUB_BUTTON_RIGHT) {

            // 20ms待って再確認
            clock.sleep(20);

            hub_button_is_pressed(&button);

            if (button & HUB_BUTTON_RIGHT) {

                // さらに20ms待って再確認
                clock.sleep(20);

                hub_button_is_pressed(&button);

                if (button & HUB_BUTTON_RIGHT) {

                    // 3回連続で右ボタンが確認できたので終了
                    char msg[32];
                    sprintf(msg, "N=%d", data_counter);

                    hub_display_text_scroll(msg, 100);

                    break;
                }
            }
        }

        // ------------------------------------------------------------
        // ★追加：約10秒ごとに現在の保存件数を表示
        // FULLに到達した後はFULL表示を優先する
        // ------------------------------------------------------------
        if (!full_reached) {

            display_timer++;

            if (display_timer >= DISPLAY_INTERVAL_LOOPS) {

                char msg[32];
                sprintf(msg, "N=%d", data_counter);

                hub_display_text_scroll(msg, 100);

                // 次の表示に向けてカウンターをリセット
                display_timer = 0;
            }
        }

        clock.sleep(10);
    }

    // ------------------------------------------------------------
    // 2. ループ終了後、USBシリアルで一括送信
    // ------------------------------------------------------------

    leftWheel.setPower(0);
    rightWheel.setPower(0);

    FILE *fp = serial_open_newlib_file(SIO_USB_PORTID);

    // USBシリアルの準備時間
    clock.sleep(3000);

    // 保存されたRGBデータを一括送信
    for (int i = 0; i < data_counter; i++) {

        fprintf(
            fp,
            "%d,%d,%d\n",
            r_array[i],
            g_data_array[i],
            b_array[i]
        );

        clock.sleep(10);
    }

    // 送信終了
    fprintf(fp, "DONE\n");

    fclose(fp);
}