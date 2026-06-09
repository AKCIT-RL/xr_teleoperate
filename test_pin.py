import os
import sys
import pinocchio as pin
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
from teleop.robot_control.robot_arm_ik import G1_29_ArmIK

ik = G1_29_ArmIK(Visualization=False)
model = ik.reduced_robot.model
print("Reduced model nq:", model.nq)
for i in range(1, model.njoints):
    print(f"Joint {i}: {model.names[i]}")

