#!/usr/bin/env python
# coding: utf-8
import smbus
import math
import logging

logger = logging.getLogger(__name__)
class YB_Pcb_Car(object):

    def get_i2c_device(self, address, i2c_bus):
        self._addr = address
        if i2c_bus is None:
            return smbus.SMBus(1)
        else:
            return smbus.SMBus(i2c_bus)

    def __init__(self):
        # Create I2C device.
        self._device = self.get_i2c_device(0x16, 1)

    def write_u8(self, reg, data):
        try:
            self._device.write_byte_data(self._addr, reg, data)
        except Exception as exc:
            logger.warning('write_u8 I2C error: %s', exc)

    def write_reg(self, reg):
        try:
            self._device.write_byte(self._addr, reg)
        except Exception as exc:
            logger.warning('write_reg I2C error: %s', exc)

    def write_array(self, reg, data):
        try:
            # self._device.write_block_data(self._addr, reg, data)
            self._device.write_i2c_block_data(self._addr, reg, data)
        except Exception as exc:
            logger.warning('write_array I2C error: %s', exc)

    def Ctrl_Car(self, l_dir, l_speed, r_dir, r_speed):
        try:
            reg = 0x01
            data = [l_dir, l_speed, r_dir, r_speed]
            self.write_array(reg, data)
        except Exception as exc:
            logger.warning('Ctrl_Car I2C error: %s', exc)
            
    def Control_Car(self, speed1, speed2):
        try:
            if speed1 < 0:
                dir1 = 0
            else:
                dir1 = 1
            if speed2 < 0:
                dir2 = 0
            else:
                dir2 = 1 
            
            self.Ctrl_Car(dir1, int(math.fabs(speed1)), dir2, int(math.fabs(speed2)))
        except Exception as exc:
            logger.warning('Control_Car I2C error: %s', exc)


    def Car_Run(self, speed1, speed2):
        try:
            self.Ctrl_Car(1, speed1, 1, speed2)
        except Exception as exc:
            logger.warning('Car_Run I2C error: %s', exc)

    def Car_Stop(self):
        try:
            reg = 0x02
            self.write_u8(reg, 0x00)
        except Exception as exc:
            logger.warning('Car_Stop I2C error: %s', exc)

    def Car_Back(self, speed1, speed2):
        try:
            self.Ctrl_Car(0, speed1, 0, speed2)
        except Exception as exc:
            logger.warning('Car_Back I2C error: %s', exc)

    def Car_Left(self, speed1, speed2):
        try:
            # Differential steering while moving forward.
            # speed1 = left wheel, speed2 = right wheel
            self.Ctrl_Car(1, speed1, 1, speed2)
        except Exception as exc:
            logger.warning('Car_Left I2C error: %s', exc)

    def Car_Right(self, speed1, speed2):
        try:
            # Differential steering while moving forward.
            # speed1 = left wheel, speed2 = right wheel
            self.Ctrl_Car(1, speed1, 1, speed2)
        except Exception as exc:
            logger.warning('Car_Right I2C error: %s', exc)

    def Car_Spin_Left(self, speed1, speed2):
        try:
            self.Ctrl_Car(0, speed1, 1, speed2)
        except Exception as exc:
            logger.warning('Car_Spin_Left I2C error: %s', exc)

    def Car_Spin_Right(self, speed1, speed2):
        try:
            self.Ctrl_Car(1, speed1, 0, speed2)
        except Exception as exc:
            logger.warning('Car_Spin_Right I2C error: %s', exc)

    def Ctrl_Servo(self, id, angle):
        try:
            reg = 0x03
            if angle < 0:
                angle = 0
            elif angle > 180:
                angle = 180
            data = [id, angle]
            self.write_array(reg, data)
        except Exception as exc:
            logger.warning('Ctrl_Servo I2C error: %s', exc)

