import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

import teleop.robot_control.robot_arm as robot_arm
import unitree_sdk2py
print("robot_arm path:", robot_arm.__file__)
print("unitree_sdk2py path:", unitree_sdk2py.__file__)
