import sys
import os
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append(os.path.join(current_dir, 'teleop', 'robot_control', 'inspire_hand_ws', 'unitree_sdk2_python'))

from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_

msg = unitree_hg_msg_dds__LowCmd_()
val = np.array([2.71])[0]

try:
    msg.motor_cmd[15].q = val
    print("Numpy assign:", msg.motor_cmd[15].q, type(msg.motor_cmd[15].q))
except Exception as e:
    print("Exception on Numpy assign:", e)

