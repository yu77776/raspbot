# Runtime Motion Tuning

PC motion parameters are hot-loaded from:

`E:\毕设\raspbot1\motion_tuning.json`

The PC client checks this file while running. After editing and saving the file,
changes are applied automatically without restarting the PC program or the car.

Useful first parameters:

| Symptom | Change |
| --- | --- |
| Servo follows too slowly | Increase `servo_kp_x` slightly |
| Servo shakes around target | Decrease `servo_kp_x` or increase `servo_dead_zone` |
| Servo overshoots | Decrease `servo_kp_x`, decrease `servo_out_max_x`, or increase `servo_kd_x` slightly |
| Body turns too fast | Decrease `body_speed_max` or `body_kp` |
| Body starts turning too easily | Increase `body_dead_zone` |
| Body does not turn enough | Increase `body_kp` or decrease `body_dead_zone` |
| Forward/backward distance follow jitters | Increase `follow_cooldown_sec` or `follow_hysteresis` |
| Distance follow moves too long | Decrease `follow_max_action_sec` |

Safe tuning order:

1. Keep `enable_motor_control=false`; tune `servo_kp_x`, `servo_kd_x`, `servo_out_max_x`.
2. Set `enable_motor_control=true`; tune `body_kp`, `body_dead_zone`, `body_speed_max`.
3. Tune distance follow with `follow_dist_near`, `follow_dist_far`, and `follow_cooldown_sec`.

The OpenCV video overlay shows the main live tuning values.
