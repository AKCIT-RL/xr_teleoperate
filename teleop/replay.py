import time
import json
import argparse
import numpy as np
from multiprocessing import Value, Array, Lock
import threading
import logging_mp
logging_mp.basic_config(level=logging_mp.INFO)
logger_mp = logging_mp.get_logger(__name__)

import os
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from unitree_sdk2py.core.channel import ChannelFactoryInitialize # dds
from teleop.robot_control.robot_arm import G1_29_ArmController, G1_23_ArmController, H1_2_ArmController, H1_ArmController
from teleop.robot_control.robot_arm_ik import G1_29_ArmIK, G1_23_ArmIK, H1_2_ArmIK, H1_ArmIK
from teleop.utils.motion_switcher import MotionSwitcher, LocoClientWrapper
from sshkeyboard import listen_keyboard, stop_listening

# for simulation
from unitree_sdk2py.core.channel import ChannelPublisher
from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_

# State machine variables and functions ============================

START          = False  # Enable to start robot following VR user motion
STOP           = False  # Enable to begin system exit procedure
READY          = False  # Ready to (1) enter START state, (2) enter RECORD_RUNNING state

def on_press(key):
    global STOP, START, READY
    if key == 'r':
        START = True
    elif key == 'q':
        START = False
        STOP = True
    else:
        logger_mp.warning(f"[on_press] {key} was pressed, but no action is defined for this key.")

def get_state() -> dict:
    """Return current heartbeat state"""
    global START, STOP, READY
    return {
        "START": START,
        "STOP": STOP,
        "READY": READY,        
    }

# =================================================================
 

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    
    # basic control parameters
    parser.add_argument('--frequency', type = float, default = 30.0, help = 'control and record \'s frequency')
    parser.add_argument('--input-mode', type=str, choices=['hand', 'controller'], default='hand', help='Select XR device input tracking source')
    parser.add_argument('--arm', type=str, choices=['G1_29', 'G1_23', 'H1_2', 'H1'], default='G1_29', help='Select arm controller')
    parser.add_argument('--ee', type=str, choices=['dex1', 'dex3', 'inspire_ftp', 'inspire_dfx', 'brainco'], help='Select end effector controller')
    parser.add_argument('--network-interface', type=str, default=None, help='Network interface for dds communication, e.g., eth0, wlan0. If None, use default interface.')
    # mode flags
    parser.add_argument('--motion', action = 'store_true', help = 'Enable motion control mode')
    parser.add_argument('--sim', action = 'store_true', help = 'Enable isaac simulation mode')
    
    # record mode and task info
    parser.add_argument('--path', type = str, default = '', help = 'path to reproduce movements')
    
    # dont need it for now
    # parser.add_argument('--task-goal', type = str, default = 'pick up cube.', help = 'task goal for recording at json file')
    # parser.add_argument('--task-desc', type = str, default = 'task description', help = 'task description for recording at json file')
    # parser.add_argument('--task-steps', type = str, default = 'step1: do this; step2: do that;', help = 'task steps for recording at json file')

    # get args
    args = parser.parse_args()
    logger_mp.info(f"args: {args}")

    # Process arguments and load appropriate classes

    try:
        if args.sim:
            ChannelFactoryInitialize(1, networkInterface=args.network_interface)
        else:
            ChannelFactoryInitialize(0, networkInterface=args.network_interface)

        listen_keyboard_thread = threading.Thread(target=listen_keyboard, 
                                                      kwargs={"on_press": on_press, "until": None, "sequential": False,}, 
                                                      daemon=True)
        listen_keyboard_thread.start()

        if args.motion:
            if args.input_mode == "controller":
                if args.sim:
                    print("### Initializing simulation locomotion publisher...")
                    sim_loco_publisher = ChannelPublisher("rt/run_command/cmd", String_)
                    sim_loco_publisher.Init()
                    print("### publisher initialized")
                else:
                    print("Initializing LocoClientWrapper...")
                    loco_wrapper = LocoClientWrapper()
        else:
            motion_switcher = MotionSwitcher()
            status, result = motion_switcher.Enter_Debug_Mode()
            logger_mp.info(f"Enter debug mode: {'Success' if status == 0 else 'Failed'}")

        # arm
        if args.arm == "G1_29":
            arm_ik = G1_29_ArmIK()
            arm_ctrl = G1_29_ArmController(motion_mode=args.motion, simulation_mode=args.sim)
        elif args.arm == "G1_23":
            arm_ik = G1_23_ArmIK()
            arm_ctrl = G1_23_ArmController(motion_mode=args.motion, simulation_mode=args.sim)
        elif args.arm == "H1_2":
            arm_ik = H1_2_ArmIK()
            arm_ctrl = H1_2_ArmController(motion_mode=args.motion, simulation_mode=args.sim)
        elif args.arm == "H1":
            arm_ik = H1_ArmIK()
            arm_ctrl = H1_ArmController(simulation_mode=args.sim)

        if args.ee == "dex3":
            from teleop.robot_control.robot_hand_unitree import Dex3_1_Controller
            left_hand_pos_array = Array('d', 75, lock = True)      # [input] unused for now, but can be used for future features like recording hand positions during replay
            right_hand_pos_array = Array('d', 75, lock = True)     # [input] unused for now, but can be used for future features like recording hand positions during replay
            hand_ctrl = Dex3_1_Controller(left_hand_pos_array, right_hand_pos_array, simulation_mode=args.sim, replay=True)
        elif args.ee == "dex1":
            from teleop.robot_control.robot_hand_unitree import Dex1_1_Gripper_Controller
            left_gripper_value = Value('d', 0.0, lock=True)        # [input] unused for now, but can be used for future features like recording gripper positions during replay
            right_gripper_value = Value('d', 0.0, lock=True)       # [input] unused for now, but can be used for future features like recording gripper positions during replay
            gripper_ctrl = Dex1_1_Gripper_Controller(left_gripper_value, right_gripper_value, simulation_mode=args.sim, replay=True)
        elif args.ee == "inspire_dfx":
            from teleop.robot_control.robot_hand_inspire import Inspire_Controller_DFX
            left_hand_pos_array = Array('d', 75, lock = True)      # [input] unused for now, but can be used for future features like recording hand positions during replay
            right_hand_pos_array = Array('d', 75, lock = True)     # [input] unused for now, but can be used for future features like recording hand positions during replay
            hand_ctrl = Inspire_Controller_DFX(left_hand_pos_array, right_hand_pos_array, simulation_mode=args.sim, replay=True)
        elif args.ee == "inspire_ftp":
            from teleop.robot_control.robot_hand_inspire import Inspire_Controller_FTP
            left_hand_pos_array = Array('d', 75, lock = True)      # [input] unused for now, but can be used for future features like recording hand positions during replay
            right_hand_pos_array = Array('d', 75, lock = True)     # [input] unused for now, but can be used for future features like recording hand positions during replay
            hand_ctrl = Inspire_Controller_FTP(left_hand_pos_array, right_hand_pos_array, simulation_mode=args.sim, replay=True)
        elif args.ee == "brainco":
            from teleop.robot_control.robot_hand_brainco import Brainco_Controller
            left_hand_pos_array = Array('d', 75, lock = True)      # [input] unused for now, but can be used for future features like recording hand positions during replay
            right_hand_pos_array = Array('d', 75, lock = True)     # [input] unused for now, but can be used for future features like recording hand positions during replay
            hand_ctrl = Brainco_Controller(left_hand_pos_array, right_hand_pos_array, simulation_mode=args.sim, replay=True)
        else:
            pass

        if args.sim:
            reset_pose_publisher = ChannelPublisher("rt/reset_pose/cmd", String_)
            reset_pose_publisher.Init()
            from teleop.utils.sim_state_topic import start_sim_state_subscribe
            sim_state_subscriber = start_sim_state_subscribe()

        # Read the replay file and store commands in an appropriate data structure

        task_path = args.path
        # Check if the directory exists
        if not os.path.exists(task_path):
            logger_mp.error(f"Task file location {task_path} does not exist.")
            raise FileNotFoundError(f"Task file location {task_path} not found.")
        
        # Load JSON data
        with open(task_path, 'r', encoding='utf-8') as f:
            episode_data = json.load(f)
        
        # Extract the list of steps (each step contains 'actions' and other data)
        steps = episode_data['data']
        
        logger_mp.info(f"Loaded {len(steps)} steps from {task_path}.")
        
        # Store in an appropriate structure: list of actions per step
        replay_actions = [step['actions'] for step in steps]
        
        # Optional: also store states if needed for validation
        replay_states = [step['states'] for step in steps]
    
        # Implement the control loop respecting the frequency passed in arguments.
        logger_mp.info("-------------------------------------")
        logger_mp.info("Press [r] to start replay, [q] to quit")
        if args.motion and args.input_mode == "controller":
            logger_mp.warning("⚠️  IMPORTANT: Motion mode activated, the robot will follow the recorded locomotion commands.")

        READY = True
        while not START:
            time.sleep(0.1)

        logger_mp.info("Reproducing recorded movements...")

        for step_actions in replay_actions:
            start_time = time.time()

            # get hands action
            if (args.ee == "dex3" or args.ee == "inspire_dfx" or args.ee == "inspire_ftp" or args.ee == "brainco") and args.input_mode == "hand":
                left_hand_action = step_actions['left_ee']['qpos']
                right_hand_action = step_actions['right_ee']['qpos']
                hand_ctrl.ctrl_dual_hand(left_hand_action, right_hand_action)

            elif args.ee == "dex1":
                left_ee_action = step_actions['left_ee']['qpos'][0]
                right_ee_action = step_actions['right_ee']['qpos'][0]
                dual_gripper_action = [left_ee_action, right_ee_action]
                gripper_ctrl.ctrl_dual_gripper(dual_gripper_action)

            else:
                pass
            
            if args.input_mode == "controller" and args.motion:
                loco_cmd = step_actions['body']['qpos']
                
                if args.sim:
                    loco_cmd = [idx/0.3 for idx in loco_cmd]  # scale up the velocity command for simulation, since the sim robot can handle higher velocity
                    loco_cmd.append(0.8)
                    commands_str = str(loco_cmd)
                    # print(commands_str)
                    msg = String_(data=commands_str)
                    sim_loco_publisher.Write(msg)

                else:
                    # https://github.com/unitreerobotics/xr_teleoperate/issues/135, control, limit velocity to within 0.3
                    if len(loco_cmd) >= 3:
                        loco_wrapper.Move(*loco_cmd)
                    else:
                        logger_mp.warning(f"Locomotion command has insufficient dimensions: expected at least 3, got {len(loco_cmd)}. Command: {loco_cmd}")
                    
            # get arms action
            sol_q = np.array(step_actions['left_arm']['qpos'] + step_actions['right_arm']['qpos'])
            sol_tauf = np.zeros(sol_q.shape)  # placeholder, since we dont have tau_f data recorded, but arm controller step function requires it as input

            arm_ctrl.ctrl_dual_arm(sol_q, sol_tauf)
            current_time = time.time()
            time_elapsed = current_time - start_time
            sleep_time = max(0, (1 / args.frequency) - time_elapsed)
            time.sleep(sleep_time)
            logger_mp.debug(f"main process sleep: {sleep_time}")

            if STOP: break
    
    # Finishing up and exiting
    except KeyboardInterrupt:
            logger_mp.info("KeyboardInterrupt received, exiting...")
    except Exception as e:
        import traceback
        logger_mp.error("Unhandled exception in replay.py: %s", e, exc_info=True)
        traceback.print_exc()
        raise
    finally:
        try:
            arm_ctrl.ctrl_dual_arm_go_home()
        except Exception as e:
            logger_mp.error(f"Failed to move arms to home: {e}")

        try:
            stop_listening()
            listen_keyboard_thread.join(timeout=1.0)
        except Exception as e:
            logger_mp.error(f"Failed to stop keyboard listener: {e}")

        try:
            if args.motion and not args.sim:
                status, result = motion_switcher.Exit_Debug_Mode()
                logger_mp.info(f"Exit debug mode: {'Success' if status is not None else 'Failed'}")
        except Exception as e:
            logger_mp.error(f"Failed to exit debug mode: {e}")

        try:
            if args.sim:
                sim_state_subscriber.stop_subscribe()
        except Exception as e:
            logger_mp.error(f"Failed to stop sim state subscriber: {e}")

        logger_mp.info("Replay script finished.")

# python replay.py --input-mode=controller --arm=G1_29 --ee=dex1 --motion --sim --path=utils/data/pick_cylinder/episode_0000/data.json 