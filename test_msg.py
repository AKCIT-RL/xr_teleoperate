import sys
import os

# Append paths just like teleop_hand_and_arm.py
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(current_dir)
sys.path.append(os.path.join(current_dir, 'teleop'))
sys.path.append(os.path.join(current_dir, 'teleop', 'robot_control', 'inspire_hand_ws', 'unitree_sdk2_python'))

from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from enum import IntEnum

class G1_29_JointArmIndex(IntEnum):
    kLeftShoulderPitch = 15

msg = unitree_hg_msg_dds__LowCmd_()
msg.motor_cmd[15].q = 3.14

print("Before Enum assign:", msg.motor_cmd[15].q)

# Test if Enum index works
try:
    msg.motor_cmd[G1_29_JointArmIndex.kLeftShoulderPitch].q = 2.71
    print("After Enum assign:", msg.motor_cmd[15].q)
except Exception as e:
    print("Exception on Enum assign:", e)

