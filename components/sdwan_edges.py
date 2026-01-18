
import time
from typing import Optional

import sdwan_config as settings
from utils.netmiko import (
    connect_to_device,
    push_config_from_file,
    push_initial_config,
)
from utils.output import Output
from utils.sdwan_sdk import SdkCallError, sdk_call_json, sdk_call_raw
from utils.vshell import read_file_vshell, run_vshell_cmd, write_file_vshell

"""
## STEP 1 - create 6 PAYG licenses
### API call towards the Manager (vManage) to create PAYG licenses. In the xample below, we create 6 licenses.
Description : Create PAYG licenses on Manager GUI via API
endpoint:
https://10.194.58.14/dataservice/system/device/generate-payg
Method: POST
payload:
{"numPaygDevices":6,"validity":"valid","organization":"ipf-netlab"}
response:
{
    "vedgeListAddMsg": "Number of PAYG vEdges added successfully: 6",
    "vedgeListAddStatus": "PAYG vEdge list added successfully",
    "id": "3acd802a-8371-4f49-8756-c41fe41429cc",
    "activityList": "[Number of PAYG vEdges added successfully: 6, Added PAYG vEdges (chassis Id, serial number): ,  - C8K-PAYG-0a7-9af2-4e03-a363-282107ffc9c8, f4e24061990342a99c289254cd91316e,  - C8K-PAYG-eae-82bd-4ed0-9aa2-f6f283965efa, df21597b9b6f474b85674d140f99aa50,  - C8K-PAYG-40a-fadb-4241-aea4-5cdd065bfb54, 343e33e95f98411cb1d193ef06e07831,  - C8K-PAYG-995-1c4d-4a33-b552-b548f05f734e, 6112bb519fc94d05ba81aa38584d825c,  - C8K-PAYG-0a3-b756-4bf4-b8bb-b0766325dec9, c825c0f59def49fe9fe68ce13fb6ada0,  - C8K-PAYG-909-8793-4ed5-bb00-2a4dd397d191, 35c183a3d39f403dba5d396c82d68e53]"
}

Pause for 30s or 1min, to let the Manager process the new licenses. The response should be stored in a variable, maybe dict or list of dict, so we can assign license from that pool when required.

### Optional (not sure we need this yet): Get list of vEdges

we may not need it this, as we already have the mapping between UUID and serial number from the previous API call.

endpoint:
https://10.194.58.14/dataservice/system/device/vedges
method: GET
response:
{
    "header": {
    [...]
    },
    "data": [
        {
            "deviceType": "vedge",
            "serialNumber": "f4e24061990342a99c289254cd91316e",
            "uuid": "C8K-PAYG-0a7-9af2-4e03-a363-282107ffc9c8",
            "managementSystemIP": "0.0.0.0",
            "chasisNumber": "C8K-PAYG-0a7-9af2-4e03-a363-282107ffc9c8",
            "configOperationMode": "cli",
            "deviceModel": "vedge-C8000V",
            "deviceState": "READY",
            "validity": "valid",
            "hardwareVedge": false,
            "vedgeCertificateState": "tokengenerated",
            "personality": "vedge",
            "uploadSource": "Generated for Pay as you Go",
            "subjectSerialNumber": "",
            "solution": "sdwan",
            "lifeCycleRequired": true,
            "expirationDate": "NA",
            "hardwareCertSerialNumber": "NA",
            "id": "NA",
            "tags": [],
            "draftMode": "Disabled",
            "device-lock": "No",
            "managed-by": "Unmanaged"
        },
        {
            "deviceType": "vedge",
            "serialNumber": "df21597b9b6f474b85674d140f99aa50",
            "uuid": "C8K-PAYG-eae-82bd-4ed0-9aa2-f6f283965efa",
            "managementSystemIP": "0.0.0.0",
            "chasisNumber": "C8K-PAYG-eae-82bd-4ed0-9aa2-f6f283965efa",
            "configOperationMode": "cli",
            "deviceModel": "vedge-C8000V",
            "deviceState": "READY",
            "validity": "valid",
            "hardwareVedge": false,
            "vedgeCertificateState": "tokengenerated",
            "personality": "vedge",
            "uploadSource": "Generated for Pay as you Go",
            "subjectSerialNumber": "",
            "solution": "sdwan",
            "lifeCycleRequired": true,
            "expirationDate": "NA",
            "hardwareCertSerialNumber": "NA",
            "id": "NA",
            "tags": [],
            "draftMode": "Disabled",
            "device-lock": "No",
            "managed-by": "Unmanaged"
        },
        {
            "deviceType": "vedge",
            "serialNumber": "343e33e95f98411cb1d193ef06e07831",
            "uuid": "C8K-PAYG-40a-fadb-4241-aea4-5cdd065bfb54",
            "managementSystemIP": "0.0.0.0",
            "chasisNumber": "C8K-PAYG-40a-fadb-4241-aea4-5cdd065bfb54",
            "configOperationMode": "cli",
            "deviceModel": "vedge-C8000V",
            "deviceState": "READY",
            "validity": "valid",
            "hardwareVedge": false,
            "vedgeCertificateState": "tokengenerated",
            "personality": "vedge",
            "uploadSource": "Generated for Pay as you Go",
            "subjectSerialNumber": "",
            "solution": "sdwan",
            "lifeCycleRequired": true,
            "expirationDate": "NA",
            "hardwareCertSerialNumber": "NA",
            "id": "NA",
            "tags": [],
            "draftMode": "Disabled",
            "device-lock": "No",
            "managed-by": "Unmanaged"
        },
        {
            "deviceType": "vedge",
            "serialNumber": "6112bb519fc94d05ba81aa38584d825c",
            "uuid": "C8K-PAYG-995-1c4d-4a33-b552-b548f05f734e",
            "managementSystemIP": "0.0.0.0",
            "chasisNumber": "C8K-PAYG-995-1c4d-4a33-b552-b548f05f734e",
            "configOperationMode": "cli",
            "deviceModel": "vedge-C8000V",
            "deviceState": "READY",
            "validity": "valid",
            "hardwareVedge": false,
            "vedgeCertificateState": "tokengenerated",
            "personality": "vedge",
            "uploadSource": "Generated for Pay as you Go",
            "subjectSerialNumber": "",
            "solution": "sdwan",
            "lifeCycleRequired": true,
            "expirationDate": "NA",
            "hardwareCertSerialNumber": "NA",
            "id": "NA",
            "tags": [],
            "draftMode": "Disabled",
            "device-lock": "No",
            "managed-by": "Unmanaged"
        },
        {
            "deviceType": "vedge",
            "serialNumber": "c825c0f59def49fe9fe68ce13fb6ada0",
            "uuid": "C8K-PAYG-0a3-b756-4bf4-b8bb-b0766325dec9",
            "managementSystemIP": "0.0.0.0",
            "chasisNumber": "C8K-PAYG-0a3-b756-4bf4-b8bb-b0766325dec9",
            "configOperationMode": "cli",
            "deviceModel": "vedge-C8000V",
            "deviceState": "READY",
            "validity": "valid",
            "hardwareVedge": false,
            "vedgeCertificateState": "tokengenerated",
            "personality": "vedge",
            "uploadSource": "Generated for Pay as you Go",
            "subjectSerialNumber": "",
            "solution": "sdwan",
            "lifeCycleRequired": true,
            "expirationDate": "NA",
            "hardwareCertSerialNumber": "NA",
            "id": "NA",
            "tags": [],
            "draftMode": "Disabled",
            "device-lock": "No",
            "managed-by": "Unmanaged"
        },
        {
            "deviceType": "vedge",
            "serialNumber": "35c183a3d39f403dba5d396c82d68e53",
            "uuid": "C8K-PAYG-909-8793-4ed5-bb00-2a4dd397d191",
            "managementSystemIP": "0.0.0.0",
            "chasisNumber": "C8K-PAYG-909-8793-4ed5-bb00-2a4dd397d191",
            "configOperationMode": "cli",
            "deviceModel": "vedge-C8000V",
            "deviceState": "READY",
            "validity": "valid",
            "hardwareVedge": false,
            "vedgeCertificateState": "tokengenerated",
            "personality": "vedge",
            "uploadSource": "Generated for Pay as you Go",
            "subjectSerialNumber": "",
            "solution": "sdwan",
            "lifeCycleRequired": true,
            "expirationDate": "NA",
            "hardwareCertSerialNumber": "NA",
            "id": "NA",
            "tags": [],
            "draftMode": "Disabled",
            "device-lock": "No",
            "managed-by": "Unmanaged"
        }
    ]
}



## You won't Pay don't worry about it!
## there might be a mismatch when briging the Edge up, but it won't stop it from working, if following the step correctly.

## STEP 2A - Configure the Edge router (Controller Mode)

### 2A.1. Configure the Edge initial configuration (example for edge2)

warning: we will have to check that it works well with netmiko, otherwise we might have to use paramiko, or some specifics, it's very simialr to ios-xe, but could be slightly different.
in our example, port 4 is the one connected to the internet router (inet0) where the other sdwan components are connected too.

config-t
ip route 0.0.0.0 0.0.0.0 10.10.0.18
int GigabitEthernet4
ip address 10.10.0.17 255.255.255.252
no shut
exit
commit

system
system-ip 10.194.58.18
site-id 102
organization-name ipf-netlab
vbond 10.10.0.6

interface Tunnel1
ip unnumbered GigabitEthernet4
tunnel source GigabitEthernet4
tunnel mode sdwan
exit

sdwan
interface GigabitEthernet4
tunnel-interface
encapsulation ipsec
allow-service all
color public-internet
exit
commit

### 2A.2. Copy the SDWAN.pem file from the Validatoru (or Manager or Controller)

edge2#copy scp: bootflash:/sdwan/
Address or name of remote host []? 10.10.0.6
Source username [admin]? 
Source filename []? SDWAN.pem
Destination filename [/sdwan/SDWAN.pem]? 
viptela 20.15.1 


Password: 
 scp: debug1: fd 3 clearing O_NONBLOCK
 Sending file modes: C0600 1310 SDWAN.pem
! scp: debug1: fd 1 clearing O_NONBLOCK

1310 bytes copied in 3.481 secs (376 bytes/sec)
edge2#

### 2A.3. Install the certificate

request platform software sdwan root-cert-chain install bootflash:sdwan/SDWAN.pem

### 2A.4. Activate the Edge with one PAYG license

We will need to select one license from the ones created in STEP 1, and make sure we remove it from the list of usable licenses.

request platform software sdwan vedge_cloud activate chassis-number C8K-PAYG-0a7-9af2-4e03-a363-282107ffc9c8 token f4e24061990342a99c289254cd91316e



"""