# Add private transport to Cisco SD-WAN

## Task 1: Create the configuration necessary to connect to the MPLS Transport.

- Step 1: Configure the MPLS router with IP addresses
- Step 2: Detach all devices from the Current Feature Template
- Step 3: Create a New Interface Feature Template current and future devices
- Step 4: Modify the VPN0 Feature Template to accommodate 2 Static Default Routes
- Step 5: Modify the Existing Device Template to add this new transport
- Step 6: Attach both devices to the Common Device Template

### Task 3: Create a New Interface Feature Template current and future devices

Use the files in the templates_json folder, it looks like the API call should be:

Endpoint: https://10.194.58.14/dataservice/template/feature/
Method: POST
Payload: contents of custom-interface-template.json

And the response will be the id of the new template created:

{"templateId":"9ae9a3e4-172f-4a06-bcc3-095311540c08"}

For the template `custom-vpn0-template.json`, the default route next-hop variable name is currently set with "G4-nh-ip", as in our setup, GigabitEthernet4 is used for the internet transport. If you are using a different interface for the private transport, please change the variable name accordingly.

```jsonc
# in templateDefinition.ip.route.vipValue.next-hop.address
"vipVariableName": "G4-nh-ip"
```

For the template `custom-vpn0-int-g4-template.json`, the interface name is set to GigabitEthernet4. If you are using a different interface for the private transport, please change the interface name accordingly.

```jsonc
# in templateDefinition.if-name
"vipValue": "GigabitEthernet4"
# in templateDefinition.ip
"vipVariableName": "G4-ip-mask"
```

Also, in the `allow-service`, we have "all": {"vipValue": "true"} to allow all traffic. If you want to restrict traffic, you can modify this section accordingly.

