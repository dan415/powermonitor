import os
import logging
import time
import psutil
import json
import wifi
import pynvml
import tinytuya
from datetime import datetime
import sys
import atexit
import subprocess

PWD = os.path.dirname(os.path.abspath(__file__))
BASEPATH = PWD if os.name == "nt" else ""
logging.basicConfig(filename=f'{BASEPATH}monitoringLog.log', encoding='utf-8', format='%(asctime)s %(message)s',
                    level=logging.DEBUG)


DEVICE_NAME = "esmarto" # Name of the Plug device
LOW_THRESHOLD = 25 # Low bound of battery level to plug on the device
HIGH_THRESHOLD = 80 # High bound of battery level to plug off the device
SLEEP_TIME = 60 * 1 # Determines how much in minutes to wait in order to check the battery again
INIT_WAIT_TIME = SLEEP_TIME * 2 # This is the initial wait time, ideally you want to wait until the device has booted up and that king of thing
LAST_FLUSH = None # datetime storing last time the log file was flushed
error = False # True if an unexpected error occurs, used to handle the state
FLUSH_PERIOD = 60 # Period for flushing the log file
MAX_RETRIES = 5 # Max retry request executions when failure
ERROR_EXIT_VAL = -415 # Error status to exit with, I just like the number :)
GPU_PROCESS_THRESHOLD = 1 # Threshold for maximum nº of processes running in GPU, above the threshold the device will always be plugged on
ALWAYS_ON = False # Variable to determine if the plug should always be turned on
HOLD = False # Hold will halt the process temporarily


def get_parameters():
    global SLEEP_TIME, INIT_WAIT_TIME, LOW_THRESHOLD, HIGH_THRESHOLD, DEVICE_NAME, FLUSH_PERIOD, MAX_RETRIES, GPU_PROCESS_THRESHOLD, ALWAYS_ON, HOLD
    with open(f'{BASEPATH}parameters.json') as f:
        parameters = json.load(f)
    SLEEP_TIME = parameters.get('SLEEP_TIME', SLEEP_TIME)
    INIT_WAIT_TIME = parameters.get('INIT_WAIT_TIME', INIT_WAIT_TIME)
    LOW_THRESHOLD = parameters.get('LOW_THRESHOLD', LOW_THRESHOLD)
    HIGH_THRESHOLD = parameters.get('HIGH_THRESHOLD', HIGH_THRESHOLD)
    DEVICE_NAME = parameters['DEVICE_NAME']
    FLUSH_PERIOD = parameters.get("FLUSH_PERIOD", FLUSH_PERIOD)
    MAX_RETRIES = parameters.get("MAX_RETRIES", MAX_RETRIES)
    GPU_PROCESS_THRESHOLD = parameters.get('GPU_PROCESS_THRESHOLD', GPU_PROCESS_THRESHOLD)
    ALWAYS_ON = parameters.get('ALWAYS_ON', ALWAYS_ON)
    HOLD = parameters.get('HOLD', HOLD)


def get_device(name, devices):
    for device in devices:
        if device['name'] == name:
            return device
    logging.info(f"Device {name} not found")
    return None


def using_gpu():
    pynvml.nvmlInit()
    try:
        num_gpus = pynvml.nvmlDeviceGetCount()
        for gpu_id in range(num_gpus):
            handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)
            num_processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            if len(num_processes) > GPU_PROCESS_THRESHOLD:
                return True
        return False
    except pynvml.NVMLError as err:
        logging.info(err)
    finally:
        pynvml.nvmlShutdown()


def netscan(retry=0):
    global HOLD
    devices = []
    if retry > MAX_RETRIES:
        logging.info("Could not scan for devices")
        HOLD = True
    try:
        devices = tinytuya.deviceScan()
    finally:
        if len(devices) == 0:
            devices = netscan(retry + 1)
        return devices


def scan_devices():
    devices = []
    try:
        devices = netscan()
        json.dump([d for d in devices.values()], open(f'{BASEPATH}devices.json', 'w'), default=str, indent=4)
    except:
        logging.info("Could not scan for devices")

    finally:
        return devices


def needs_consuming():
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_percent = psutil.virtual_memory().percent

    logging.info(f"CPU: {cpu_percent}%")
    logging.info(f"Memory: {memory_percent}%")

    too_high_cpu = cpu_percent > 80 or memory_percent > 80
    return too_high_cpu or using_gpu()


def get_devices(from_scan=False):
    try:
        devices = json.load(open(f'{BASEPATH}devices.json'))
    except FileNotFoundError:
        logging.info("No devices.json file found")
        devices = scan_devices()
    finally:
        return devices


def connect_to_plug():
    devices = get_devices()
    if len(devices) == 0:
        return None

    device_config = get_device(DEVICE_NAME, devices)

    if device_config is None:
        return None

    return tinytuya.OutletDevice(
        dev_id=device_config['id'],
        address=device_config['ip'],
        local_key=device_config['key'],
        version=3.3
    )


def get_battery_level():
    battery = psutil.sensors_battery()
    logging.info(f"battery is {battery.percent}")
    return battery.percent, battery.power_plugged

def turn(on):
    global HOLD

    try:
        plug = connect_to_plug()
        if plug is None:
            logging.info("Could not connect to plug")

        if on:
            try:
                plug.turn_on()
                logging.info("Turned on")
            except:
                logging.info("Could not turn on plug")
                if len(scan_devices()) == 0:
                    logging.info("Something wrong with network or devices")
                    HOLD = True

        else:
            try:
                plug.turn_off()
                logging.info("Turned off")
            except:
                logging.info("Could not turn off plug")
                if len(scan_devices()) == 0:
                    logging.info("Something wrong with network or devices")
                    HOLD = True
    finally:
        # if connected_to_wifi_and_ethernet:
        #     disconnect_from_wifi()
        pass


def check_for_flush():
    check_time = datetime.now()
    if not LAST_FLUSH or ((check_time - LAST_FLUSH).seconds / 60) > FLUSH_PERIOD:
        flush()
        return check_time
    return LAST_FLUSH


def on_shutdown():
    if error:
        turn(True)
    else:
        turn(False)


def flush():
    open(f"{BASEPATH}monitoringLog.log", "w").close()


if __name__ == '__main__':
    time.sleep(INIT_WAIT_TIME)
    atexit.register(on_shutdown)
    logging.info("Started monitoring")
    while True:
        try:
            get_parameters()
            if HOLD:
                logging.info("Holding")
                time.sleep(SLEEP_TIME)
                continue
            if ALWAYS_ON:
                logging.info("Always on")
                turn(True)
                time.sleep(SLEEP_TIME)
                continue
            LAST_FLUSH = check_for_flush()
            battery_level, plugged = get_battery_level()
            if needs_consuming():
                if not plugged:
                    logging.info("Needs consuming")
                    turn(True)

            elif not (LOW_THRESHOLD < battery_level < HIGH_THRESHOLD):
                turn(battery_level < HIGH_THRESHOLD)
            else:
                logging.info("Nothing to do")
            logging.info("Sleeping")
            time.sleep(SLEEP_TIME)
        except Exception as ex:
            HOLD = True
            logging.info(ex)
            time.sleep(SLEEP_TIME)
