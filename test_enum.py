from enum import IntEnum
import numpy as np

class G1_29_JointArmIndex(IntEnum):
    kLeftShoulderPitch = 15
    kLeftShoulderRoll = 16

l = [0] * 35
for idx, id in enumerate(G1_29_JointArmIndex):
    print(id, type(id), id.value)
    l[id] = 1.0

print(l[15], l[16])
