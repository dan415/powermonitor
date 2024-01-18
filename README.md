
<h1> Battery Power Monitor</h1>


This is a simple program to monitor the battery level of a device and automatically turn on
a smart plug to charge the device when the battery level is low and turn off the smart plug when
the battery level is high, in order to preserve the battery life.


The program is designed to run as a service, for which I have implemented both a Linux and a
Windows service. The Linux service is implemented as a systemd service, while the Windows service
is implemented as a Windows service. (monitorer.py, powermonitor_win.py, respectively)


<h2>Pre Requisites</h2>

First of all, you need to create a Conda virtual environment called `powermonitor`. This can be done
by running the following command:

```bash
conda create env create -f environment.yml

```

This will create a virtual environment called `powermonitor` with all the required dependencies.



For this program to work, you need a smart plug compatible with Tuya Smart Life. You then need to confgure
a development project in the tuya cloud. In order to achieve this, follow the instructions in the
pytuya repository: https://github.com/jasonacox/tinytuya?tab=readme-ov-file.

It must be noted that the Smart Plug is only visible via the pytuya package when it is connected
to the same *Wifi* network as the device running the pytuya package. This means that if you intend to use
this program on a device connected by Ethernet, you will need to configure a rule on the IP Routing Table to force connections
to the smart plug to go through the Wifi interface. This is not covered in this document, but there are
plenty of resources online on how to achieve this.


Once you have followed the instructions, you will have generated a configuration file with the
scanning information for your smart plug. You will need to copy this file to the same directory
as the battery monitor program, it is expected to be named `devices.json`. 


<h2>Configuration</h2>

You also need to configure a configuration file for the battery monitor program. This file is
expected to be named `paramters.json` and to be located in the same directory as the battery monitor
program. The file should have the following format:

```json
{
  "ALWAYS_ON": false,
  "SLEEP_TIME": 60,
  "INIT_WAIT_TIME": 120,
  "MAX_RETRIES": 5,
  "GPU_PROCESS_THRESHOLD": 1,
  "DEVICE_NAME": "esmarto",
  "HOLD": false
}
```

The parameters are as follows:
* `ALWAYS_ON`: If set to true, the smart plug will always be on, regardless of the battery level.
* `SLEEP_TIME`: The time in seconds to wait between battery level checks.
* `INIT_WAIT_TIME`: The time in seconds to wait before starting the battery level checks.
* `MAX_RETRIES`: The maximum number of retries to attempt when communicating with the smart plug.
* `GPU_PROCESS_THRESHOLD`: The number of GPU processes that need to be running in order to consider
  the device to be in use. If the number of GPU processes is equal to or greater than this number, it is assumed
    that high performance is required and the smart plug will be turned on.
* `DEVICE_NAME`: The name of the device to monitor. This is the name that will be used to identify the device
  in the smart life app. This is the name that you gave to the device when you configured it in the smart life app, and needs
    to appear in the `devices.json` file.
* `HOLD`: If set to true, the smart plug will be turned on and will not be turned off until this parameter is set to false.
  This is useful if you want to manually control the smart plug, for example, if you want to turn it on to charge the device
    and then turn it off manually when you want to use the device. This parameters automatically sets to True if the maximum number
    of errors is reached, to avoid the smart plug being turned on and off continuously if there is a problem communicating with it.


<h2>Logs</h2>

The program will generate a log file called `monitoringLog.log` in the same directory as the program. This file
will contain information about the battery level checks and the actions taken by the program. It will automatically be flushed
every 60 minutes by default, so that the log file does not grow too large. This behaviour is controlled by the global variable
FLUSH_TIME in the source code.


<h2> Installation as a service</h2>

<h3>Linux</h3>

In order to install the program as a service in Linux, you need to copy the file `powermonitor.service` to the
`/etc/systemd/system` directory. You then need to edit the file and change the `WorkingDirectory` parameter to point
to the directory where the program is located. You also need to change the `ExecStart` parameter to point to the
location of the `monitorer.py` file, and to point to the Python executable containing the necessary dependencies. If you have followed the instructions,
the path would be the result of running (on linux):

```bash
conda env list | grep powermonitor | awk '{print $2}'
```

You can then start the service by running the following command:

```bash
sudo systemctl start powermonitor.service
```

<h3>Windows</h3>

In order to install the program as a service in Windows, you need to do the following:

```cmd

pyinstaller --onefile powermonitor_win.py
sc create service-name binPath= "path-to-executable"
sc config service-name start= auto
sc start service-name

```

Where `service-name` is the name that you want to give to the service, and `path-to-executable` is the path to the executable
generated by pyinstaller. This executable will most likely be located in the `dist` directory.






