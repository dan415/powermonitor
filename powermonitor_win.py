import atexit
import logging
import os
import subprocess
import sys
import time
from datetime import datetime

import psutil
import servicemanager
import tinytuya
import win32event
import win32service
import win32serviceutil
import json
import pynvml
import re
from pathlib import Path

import requests


class PowerMonitorService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'powermonitor'
    _svc_display_name_ = 'PowerMonitorService'
    _svc_description_ = 'Service for automatically controlling the charging behaviour of laptop'

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.event = win32event.CreateEvent(None, 0, 0, None)

        self.low_threshold = 20
        self.high_threshold = 80
        self.device_name = "esmarto"
        self.base_path = r'/proyectos/Python/powermonitor/' if os.name == "nt" else ""
        logging.basicConfig(filename=f'{self.base_path}monitoringLog.log', encoding='utf-8',
                            format='%(asctime)s %(message)s',
                            level=logging.DEBUG)
        self.sleep_time = 60 * 1
        self.init_wait_time = self.sleep_time * 2
        self.last_flush = None
        self.flush_period = 60
        self.max_retries = 5
        self.error_exit_val = -415
        self.gpu_process_threshold = 1
        self.always_on = False
        self.hold = False

    def GetAcceptedControls(self):
        result = win32serviceutil.ServiceFramework.GetAcceptedControls(self)
        result |= win32service.SERVICE_ACCEPT_PRESHUTDOWN
        return result

    def get_device(self, name, devices):
        for device in devices:
            if device['name'] == name:
                return device
        logging.info(f"Device {name} not found")
        return None

    def netscan(self, retry=0):
        devices = []
        if retry > self.max_retries:
            logging.info("Could not scan for devices")
            self.hold = True
        try:
            devices = tinytuya.deviceScan()
        finally:
            if len(devices) == 0:
                devices = self.netscan(retry + 1)
            return devices

    def scan_devices(self):
        devices = []
        try:
            devices = self.netscan()
            json.dump([d for d in devices.values()], open(f'{self.base_path}devices.json', 'w'), default=str, indent=4)
        except:
            logging.info("Could not scan for devices")

        finally:
            return devices

    def get_devices(self, from_scan=False):
        try:
            devices = json.load(open(f'{self.base_path}devices.json'))
        except FileNotFoundError:
            logging.info("No devices.json file found")
            devices = self.scan_devices()
        finally:
            return devices

    def connect_to_plug(self):
        devices = self.get_devices()
        if len(devices) == 0:
            return None

        device_config = self.get_device(self.device_name, devices)

        if device_config is None:
            return None

        return tinytuya.OutletDevice(
            dev_id=device_config['id'],
            address=device_config['ip'],
            local_key=device_config['key'],
            version=3.3
        )

    def get_battery_level(self):
        battery = psutil.sensors_battery()
        logging.info(f"Battery: {battery.percent}%")
        return battery.percent, battery.power_plugged

    def turn(self, on):
        # connected_to_wifi_and_ethernet = False
        # if self.is_ethernet_connected():
        #     try:
        #         connected_to_wifi_and_ethernet = self.connect_to_wifi()
        #     except Exception as ex:
        #         logging.info("Could not connect to wifi: " + str(ex))
        try:
            plug = self.connect_to_plug()
            if plug is None:
                logging.info("Could not connect to plug")

            if on:
                try:
                    plug.turn_on()
                    logging.info("Turned on")
                except:
                    logging.info("Could not turn on plug")
                    if len(self.scan_devices()) == 0:
                        logging.info("Something wrong with network or devices")
                        self.hold = True

            else:
                try:
                    plug.turn_off()
                    logging.info("Turned off")
                except:
                    logging.info("Could not turn off plug")
                    if len(self.scan_devices()) == 0:
                        logging.info("Something wrong with network or devices")
                        self.hold = True
        finally:
            # if connected_to_wifi_and_ethernet:
            #     self.disconnect_from_wifi()
            pass


    def using_gpu(self):
        pynvml.nvmlInit()
        try:
            num_gpus = pynvml.nvmlDeviceGetCount()
            for gpu_id in range(num_gpus):
                handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)
                num_processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                if len(num_processes) > self.gpu_process_threshold:
                    logging.info(f"GPU {gpu_id} is being used")
                    logging.info(f"Processes: {num_processes} for threshold: {self.gpu_process_threshold}")
                    return True
            return False
        except pynvml.NVMLError as err:
            logging.info(err)
        finally:
            pynvml.nvmlShutdown()

    def needs_consuming(self):
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent

        logging.info(f"CPU: {cpu_percent}%")
        logging.info(f"Memory: {memory_percent}%")

        too_high = cpu_percent > 80 or memory_percent > 80
        if too_high:
            logging.info("Too high cpu or memory usage")
        return too_high or self.using_gpu()

    def is_ethernet_connected(self):
        try:
            # Check for active network interfaces
            network_interfaces = psutil.net_if_stats()
            for interface_name, interface_stats in network_interfaces.items():
                if interface_stats.isup:
                    # Check if the interface is an Ethernet interface (e.g., Ethernet0)
                    if "Ethernet" in interface_name:
                        logging.info("Ethernet connected")
                        return True
            logging.info("Ethernet not connected")
            return False
        except Exception:
            logging.info("Error checking Ethernet connection")
            return False

    def connect_to_wifi(self):
        """Connects to a specified Wi-Fi network using subprocess."""
        result = False
        wifi_config = json.load(open(f'{self.base_path}wifi_config.json'))
        ssid = wifi_config['ssid']
        password = wifi_config['password']

        logging.info(f"Attempting to connect to: {ssid}")

        # Construct the command to connect to the Wi-Fi network
        command = ['netsh', 'wlan', 'connect', 'ssid=' + ssid, 'password=' + password]

        try:
            # Execute the command and capture the output
            output = subprocess.check_output(command).decode('utf-8')
            logging.info(output)

            # Check if the output indicates successful connection
            if 'Successfully connected to' in output:
                result = True
                logging.info("Connected to network: " + ssid)
            else:
                logging.info("Failed to connect to network: " + ssid)

        except subprocess.CalledProcessError as e:
            logging.error(f"Error connecting to Wi-Fi: {e}")

        return result

    def check_for_flush(self):
        check_time = datetime.now()
        if not self.last_flush or ((check_time - self.last_flush).seconds / 60) > self.flush_period:
            self.flush()
            return check_time
        return self.last_flush

    def on_shutdown(self):
        exit_code = 0
        if exit_code == self.error_exit_val:
            # do not trigger on error exit
            return
        else:
            self.turn(False)

    def flush(self):
        open(f"{self.base_path}monitoringLog.log", "w").close()

    def get_parameters(self):
        with open(f'{self.base_path}parameters.json') as f:
            parameters = json.load(f)
        self.sleep_time = parameters.get('SLEEP_TIME', self.sleep_time)
        logging.info(f"Sleep time: {self.sleep_time}")
        self.init_wait_time = parameters.get('INIT_WAIT_TIME', self.init_wait_time)
        logging.info(f"Init wait time: {self.init_wait_time}")
        self.low_threshold = parameters.get('LOW_THRESHOLD', self.low_threshold)
        logging.info(f"Low threshold: {self.low_threshold}")
        self.high_threshold = parameters.get('HIGH_THRESHOLD', self.high_threshold)
        logging.info(f"High threshold: {self.high_threshold}")
        self.device_name = parameters.get('DEVICE_NAME', self.device_name)
        logging.info(f"Device name: {self.device_name}")
        self.flush_period = parameters.get('FLUSH_PERIOD', self.flush_period)
        logging.info(f"Flush period: {self.flush_period}")
        self.max_retries = parameters.get('MAX_RETRIES', self.max_retries)
        logging.info(f"Max retries: {self.max_retries}")
        self.gpu_process_threshold = parameters.get('GPU_PROCESS_THRESHOLD', self.gpu_process_threshold)
        logging.info(f"GPU process threshold: {self.gpu_process_threshold}")
        self.always_on = parameters.get('ALWAYS_ON', self.always_on)
        logging.info(f"Always on: {self.always_on}")
        self.hold = parameters.get('HOLD', self.hold)
        logging.info(f"Hold: {self.hold}")

    def main(self):
        time.sleep(self.init_wait_time)
        atexit.register(self.on_shutdown)
        logging.info("Started monitoring")

        while True:
            try:
                self.get_parameters()
                if self.hold:
                    logging.info("Holding")
                    time.sleep(self.sleep_time)
                    continue
                if self.always_on:
                    logging.info("Always on")
                    self.turn(True)
                    time.sleep(self.sleep_time)
                    continue
                self.last_flush = self.check_for_flush()
                battery_level, plugged = self.get_battery_level()
                if self.needs_consuming() and not plugged:
                    logging.info("Needs consuming")
                    self.turn(True)
                else:
                    if not (self.low_threshold < battery_level < self.high_threshold):
                        self.turn(battery_level < self.high_threshold)
                    else:
                        logging.info("Nothing to do")
                logging.info("Sleeping")
                time.sleep(self.sleep_time)
            except Exception as ex:
                self.hold = True
                logging.info(ex)

    def switch_to_ethernet(self):
        """Disconnects from Wi-Fi and connects to Ethernet."""

        # Disconnect from Wi-Fi
        try:
            logging.info("Disconnecting from Wi-Fi...")
            subprocess.check_output(['netsh', 'wlan', 'disconnect'])
            logging.info("Disconnected from Wi-Fi.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error disconnecting from Wi-Fi: {e}")
            return False

        # Enable Ethernet interface
        try:
            logging.info("Enabling Ethernet interface...")
            subprocess.check_output(
                ['netsh', 'interface', 'ip', 'set', 'interface', 'Ethernet', 'admin', 'state=enabled'])
            logging.info("Ethernet interface enabled.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error enabling Ethernet interface: {e}")
            return False

        # Check if Ethernet connection is established
        try:
            output = subprocess.check_output(['netsh', 'interface', 'ip', 'show', 'addr']).decode('utf-8')
            if 'Ethernet' in output and 'DHCP Enabled' in output:
                logging.info("Connected to Ethernet.")
                return True
            else:
                logging.info("Failed to connect to Ethernet.")
                return False
        except subprocess.CalledProcessError as e:
            logging.error(f"Error checking Ethernet connection: {e}")
            return False

    def SvcDoRun(self):
        self.main()

    def SvcStop(self):
        self.on_shutdown()
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.event)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(PowerMonitorService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(PowerMonitorService)
