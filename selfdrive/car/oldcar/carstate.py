from selfdrive.car.oldcar.values import CAR, DBC
from selfdrive.can.parser import CANParser
from selfdrive.config import Conversions as CV
from common.kalman.simple_kalman import KF1D
import numpy as np


def parse_gear_shifter(can_gear, car_fingerprint):
  # TODO: Use values from DBC to parse this field
  if car_fingerprint in [CAR.CAMRYH, 
                           CAR.COROLLA]:
    if can_gear == 0x20:
      return "park"
    elif can_gear == 0x10:
      return "reverse"
    elif can_gear == 0x8:
      return "neutral"
    elif can_gear == 0x0:
      return "drive"
    elif can_gear == 0x1:
      return "sport"

  return "unknown"


def get_can_parser(CP):

  signals = [
    # sig_name, sig_address, default
    ("GEAR", "GEAR_PACKET", 0),
    ("BRAKE_PRESSED", "BRAKE_MODULE", 0),
    ("GAS_PEDAL", "GAS_PEDAL", 0),
    ("WHEEL_SPEED_FL", "WHEEL_SPEEDS", 0),
    ("WHEEL_SPEED_FR", "WHEEL_SPEEDS", 0),
    ("WHEEL_SPEED_RL", "WHEEL_SPEEDS", 0),
    ("WHEEL_SPEED_RR", "WHEEL_SPEEDS", 0),
    ("DOOR_OPEN_FL", "SEATS_DOORS", 1),
    ("DOOR_OPEN_FR", "SEATS_DOORS", 1),
    ("DOOR_OPEN_RL", "SEATS_DOORS", 1),
    ("DOOR_OPEN_RR", "SEATS_DOORS", 1),
    ("SEATBELT_DRIVER_UNLATCHED", "SEATS_DOORS", 1),
    ("TC_DISABLED", "ESP_CONTROL", 1),
    ("STEER_ANGLE", "STEER_ANGLE_SENSOR", 0),
    ("STEER_FRACTION", "STEER_ANGLE_SENSOR", 0),
    ("STEER_RATE", "STEER_ANGLE_SENSOR", 0),
    ("GAS_RELEASED", "PCM_CRUISE", 0),
    ("CRUISE_STATE", "PCM_CRUISE", 0),
    ("MAIN_ON", "PCM_CRUISE_SM", 0),
    ("MAIN_ON", "PCM_CRUISE_2", 0),
    ("SET_SPEED", "PCM_CRUISE_2", 0),
    ("LOW_SPEED_LOCKOUT", "PCM_CRUISE_2", 0),
    ("STEER_TORQUE_DRIVER", "STEER_TORQUE_SENSOR", 0),
    ("STEER_TORQUE_EPS", "STEER_TORQUE_SENSOR", 0),
    ("TURN_SIGNALS", "STEERING_LEVERS", 3),   # 3 is no blinkers
    ("LKA_STATE", "EPS_STATUS", 0),
    ("IPAS_STATE", "EPS_STATUS", 1),
    ("BRAKE_LIGHTS_ACC", "ESP_CONTROL", 0),
    ("AUTO_HIGH_BEAM", "LIGHT_STALK", 0),
  ]

  checks = [
    #("BRAKE_MODULE", 40),
    #("GAS_PEDAL", 33),
    ("WHEEL_SPEEDS", 80),
    #("STEER_ANGLE_SENSOR", 80),
    #("PCM_CRUISE", 33),
    #("PCM_CRUISE_2", 33),
    #("STEER_TORQUE_SENSOR", 50),
    #("EPS_STATUS", 25),
  ]


  return CANParser(DBC[CP.carFingerprint]['pt'], signals, checks, 0)


class CarState(object):
  def __init__(self, CP):

    self.CP = CP
    self.left_blinker_on = 0
    self.right_blinker_on = 0
    self.cruise_stalk_pull = False

    # initialize can parser
    self.car_fingerprint = CP.carFingerprint

    # vEgo kalman filter
    dt = 0.01
    # Q = np.matrix([[10.0, 0.0], [0.0, 100.0]])
    # R = 1e3
    self.v_ego_kf = KF1D(x0=np.matrix([[0.0], [0.0]]),
                         A=np.matrix([[1.0, dt], [0.0, 1.0]]),
                         C=np.matrix([1.0, 0.0]),
                         K=np.matrix([[0.12287673], [0.29666309]]))
    self.v_ego = 0.0

  def update(self, cp):
    # copy can_valid
    self.can_valid = cp.can_valid

    # update prevs, update must run once per loop


    # calc best v_ego estimate, by averaging two opposite corners
    self.v_wheel_fl = cp.vl["WHEEL_SPEEDS"]['WHEEL_SPEED_FL'] * CV.KPH_TO_MS
    self.v_wheel_fr = cp.vl["WHEEL_SPEEDS"]['WHEEL_SPEED_FR'] * CV.KPH_TO_MS
    self.v_wheel_rl = cp.vl["WHEEL_SPEEDS"]['WHEEL_SPEED_RL'] * CV.KPH_TO_MS
    self.v_wheel_rr = cp.vl["WHEEL_SPEEDS"]['WHEEL_SPEED_RR'] * CV.KPH_TO_MS
    self.v_wheel = (self.v_wheel_fl + self.v_wheel_fr + self.v_wheel_rl + self.v_wheel_rr) / 4.

    # Kalman filter
    if abs(self.v_wheel - self.v_ego) > 2.0:  # Prevent large accelerations when car starts at non zero speed
      self.v_ego_x = np.matrix([[self.v_wheel], [0.0]])

    self.v_ego_raw = self.v_wheel
    v_ego_x = self.v_ego_kf.update(self.v_wheel)
    self.v_ego = float(v_ego_x[0])
    self.a_ego = float(v_ego_x[1])
    self.standstill = not self.v_wheel > 0.001

    
    
    self.angle_steers = cp.vl["STEER_ANGLE_SENSOR"]['STEER_ANGLE'] + cp.vl["STEER_ANGLE_SENSOR"]['STEER_FRACTION']
    self.angle_steers_rate = cp.vl["STEER_ANGLE_SENSOR"]['STEER_RATE']

    # 2 is standby, 10 is active. TODO: check that everything else is really a faulty state
    self.steer_state = cp.vl["EPS_STATUS"]['LKA_STATE'] #3
    self.ipas_active = cp.vl['EPS_STATUS']['IPAS_STATE'] == 3 #0

    self.steer_torque_driver = cp.vl["STEER_TORQUE_SENSOR"]['STEER_TORQUE_DRIVER']
    self.steer_torque_motor = cp.vl["STEER_TORQUE_SENSOR"]['STEER_TORQUE_EPS']

    self.main_on = 1 #cp.vl["PCM_CRUISE_2"]['MAIN_ON'] #1
    self.v_cruise_pcm = cp.vl["PCM_CRUISE_2"]['SET_SPEED']
    
    self.pcm_acc_status = cp.vl["PCM_CRUISE"]['CRUISE_STATE'] #1

    
    self.prev_left_blinker_on = self.left_blinker_on
    self.prev_right_blinker_on = self.right_blinker_on
    self.left_blinker_on = cp.vl["STEERING_LEVERS"]['TURN_SIGNALS'] == 1
    self.right_blinker_on = cp.vl["STEERING_LEVERS"]['TURN_SIGNALS'] == 2   
    
    self.cruise_stalk_pull = cp.vl["PCM_CRUISE_SM"]['MAIN_ON'] == 1
 
    self.brake_pressed = cp.vl["BRAKE_MODULE"]['BRAKE_PRESSED']
      
      
      #Below values never update
      
      

    can_gear = 0x0 # Always in drive   cp.vl["GEAR_PACKET"]['GEAR']
      
    self.low_speed_lockout = 0 #cp.vl["PCM_CRUISE_2"]['LOW_SPEED_LOCKOUT'] == 2
    self.brake_lights = False #bool(cp.vl["ESP_CONTROL"]['BRAKE_LIGHTS_ACC'] or self.brake_pressed) #This one causes controlsd fail when "0", expected bool
    self.gas_pressed = 0 #not cp.vl["PCM_CRUISE"]['GAS_RELEASED']     
    self.user_brake = 0      
    self.brake_error = 0      
    self.steer_error = False #cp.vl["EPS_STATUS"]['LKA_STATE'] not in [1, 5] #0      
    self.steer_override = False #abs(cp.vl["STEER_TORQUE_SENSOR"]['STEER_TORQUE_DRIVER']) > 100 #This causes controlsd error when "0", expected bool    
    self.gear_shifter = 0 #parse_gear_shifter(can_gear, self.car_fingerprint)      
    self.brake_pressed = 0 #cp.vl["BRAKE_MODULE"]['BRAKE_PRESSED']
    self.pedal_gas = 0 #cp.vl["GAS_PEDAL"]['GAS_PEDAL']
    self.car_gas = 0 #self.pedal_gas
    self.esp_disabled = 0 #cp.vl["ESP_CONTROL"]['TC_DISABLED']      
    self.door_all_closed = 1 #not any([cp.vl["SEATS_DOORS"]['DOOR_OPEN_FL'], cp.vl["SEATS_DOORS"]['DOOR_OPEN_FR'],
                                    #cp.vl["SEATS_DOORS"]['DOOR_OPEN_RL'], cp.vl["SEATS_DOORS"]['DOOR_OPEN_RR']])
    self.seatbelt = 1 #not cp.vl["SEATS_DOORS"]['SEATBELT_DRIVER_UNLATCHED']      

    self.generic_toggle = bool(cp.vl["LIGHT_STALK"]['AUTO_HIGH_BEAM'])    
      
      
      
      
      