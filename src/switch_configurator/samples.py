"""Synthetic CLI examples for demos/tests, NOT recordings from qualified hardware."""

SAMPLES = {
    "arista_eos": {
        "show version": "Arista DCS-7050SX3-48YC8\nModel: DCS-7050SX3-48YC8\nSoftware image version: 4.32.2F",
        "show running-config": "hostname LAB-EOS\nvlan 10\n   name STAFF\nvlan 20\n   name VOICE\ninterface Ethernet1\n   description Desk 1\n   switchport mode access\n   switchport access vlan 10\ninterface Ethernet2\n   description Uplink\n   switchport mode trunk\n   switchport trunk native vlan 1\n   switchport trunk allowed vlan 10,20\nend",
        "show interfaces status": "Port Name Status Vlan Duplex Speed Type\nEt1 Desk-1 connected 10 full 1G 1000BASE-T\nEt2 Uplink connected trunk full 10G 10GBASE-SR",
        "show vlan": "VLAN Name Status Ports\n1 default active\n10 STAFF active Et1\n20 VOICE active",
    },
    "cisco_nxos": {
        "show version": "Cisco Nexus Operating System (NX-OS) Software\nModel: N9K-C93180YC-FX\nNXOS: version 10.3(4a)",
        "show running-config": "!Command: show running-config\nhostname LAB-NXOS\nvlan 10\n  name STAFF\nvlan 20\n  name VOICE\ninterface Ethernet1/1\n  description Desk 1\n  switchport\n  switchport mode access\n  switchport access vlan 10\n  no shutdown\ninterface Ethernet1/2\n  description Uplink\n  switchport\n  switchport mode trunk\n  switchport trunk native vlan 1\n  switchport trunk allowed vlan 10,20\n  no shutdown\n",
        "show interfaces status": "Port Name Status Vlan Duplex Speed Type\nEth1/1 Desk-1 connected 10 full 1000 1000base-T\nEth1/2 Uplink connected trunk full 10G 10Gbase-SR",
        "show vlan brief": "VLAN Name Status Ports\n1 default active\n10 STAFF active Eth1/1\n20 VOICE active",
    },
    "aruba_cx": {
        "show version": "ArubaOS-CX\nModel: JL725A\nVersion : FL.10.13.1000",
        "show running-config": "hostname LAB-CX\nvlan 1\nvlan 10\n    name STAFF\nvlan 20\n    name VOICE\ninterface 1/1/1\n    no shutdown\n    description Desk 1\n    no routing\n    vlan access 10\ninterface 1/1/2\n    no shutdown\n    description Uplink\n    no routing\n    vlan trunk native 1\n    vlan trunk allowed 10,20\n",
        "show interface brief": "Port Native VLAN Mode Type Enabled Status Reason Speed Description\n1/1/1 10 access 1GbT yes up 1000 Desk-1\n1/1/2 1 trunk SFP+ yes up 10000 Uplink",
        "show vlan": "VLAN Name Status Reason Type Interfaces\n1 DEFAULT_VLAN_1 up ok static\n10 STAFF up ok static 1/1/1\n20 VOICE up ok static",
    },
    "dell_os10": {
        "show version": "Dell SmartFabric OS10 Enterprise\nModel: S5248F-ON\nOS Version: 10.5.5.5",
        "show running-configuration": "! Version 10.5.5.5\nhostname LAB-OS10\ninterface vlan 1\n vlan-name default\ninterface vlan 10\n vlan-name STAFF\ninterface vlan 20\n vlan-name VOICE\ninterface ethernet1/1/1\n description Desk 1\n no shutdown\n switchport mode access\n switchport access vlan 10\ninterface ethernet1/1/2\n description Uplink\n no shutdown\n switchport mode trunk\n switchport access vlan 1\n switchport trunk allowed vlan 10,20\n",
        "show interface status": "Port Description Status Speed Duplex Mode Vlan Tagged-Vlans\nEth 1/1/1 Desk-1 up 1G full A 10 -\nEth 1/1/2 Uplink up 10G full T 1 10,20",
        "show vlan": "NUM Status Description Q Ports\n* 1 Active U Eth1/1/2\n10 Active U Eth1/1/1\n20 Active T Eth1/1/2",
    },
    "tplink_jetstream": {
        "show system-info": "System Description - TP-Link JetStream Gigabit L2 Managed Switch\nModel: TL-SG3428\nFirmware Version: 1.1.0\nSystem Name - LAB-JETSTREAM",
        "show running-config": "hostname LAB-JETSTREAM\nvlan 1\n name System-VLAN\nvlan 10\n name STAFF\nvlan 20\n name VOICE\ninterface gigabitEthernet 1/0/1\n description \"Desk 1\"\n switchport general allowed vlan 10 untagged\n switchport pvid 10\n no switchport general allowed vlan 1\ninterface gigabitEthernet 1/0/2\n description Uplink\n switchport general allowed vlan 10,20 tagged\n switchport pvid 1\nend",
        "show interface status": "Port Status Speed Duplex FlowCtrl Jumbo Active-Medium\nGi1/0/1 LinkUp 1000M Full Disable Enable Copper\nGi1/0/2 LinkUp 1000M Full Disable Enable Copper",
        "show interface switchport": "Port LAG Type PVID\nGi1/0/1 N/A General 10\nGi1/0/2 N/A General 1",
        "show vlan": "VLAN 1\nName: System-VLAN\nVLAN 10\nName: STAFF\nVLAN 20\nName: VOICE",
    },
    "extreme_exos": {
        "show version": "ExtremeXOS version 32.7.1.9\nModel: X440G2-24p-10G4",
        "show configuration": '# Module vlan configuration.\nconfigure snmp sysName "LAB-EXOS"\ncreate vlan "STAFF"\nconfigure vlan STAFF tag 10\ncreate vlan "VOICE"\nconfigure vlan VOICE tag 20\nconfigure vlan Default delete ports 1\nconfigure vlan STAFF add ports 1 untagged\nconfigure vlan STAFF add ports 2 tagged\nconfigure vlan VOICE add ports 2 tagged\nconfigure ports 1 description-string "Desk 1"\nconfigure ports 2 description-string "Uplink"\n# End of configuration',
        "show ports no-refresh": "Port Display String VLAN Name Port State Link State Speed Duplex\n1 Desk-1 STAFF E A 1000 FULL\n2 Uplink (3) E A 10000 FULL",
        "show vlan": "Name VID Protocol Addr Flags Proto Ports Virtual\nDefault 1 -------------------------------- ANY 2/2 VR-Default\nSTAFF 10 -------------------------------- ANY 2/2 VR-Default\nVOICE 20 -------------------------------- ANY 1/1 VR-Default",
    },
    "juniper_junos": {
        "show version": "Hostname: LAB-JUNOS\nModel: ex3400-24p\nJunos: 23.4R2-S1.6",
        "show configuration | display set | no-more": 'set system host-name LAB-JUNOS\nset vlans default vlan-id 1\nset vlans STAFF vlan-id 10\nset vlans VOICE vlan-id 20\nset interfaces ge-0/0/0 description "Desk 1"\nset interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access\nset interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members STAFF\nset interfaces ge-0/0/1 description Uplink\nset interfaces ge-0/0/1 native-vlan-id 1\nset interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\nset interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ STAFF VOICE ]',
        "show interfaces terse | no-more": "Interface Admin Link Proto Local Remote\nge-0/0/0 up up\nge-0/0/0.0 up up eth-switch\nge-0/0/1 up up\nge-0/0/1.0 up up eth-switch",
        "show vlans | no-more": "Routing instance VLAN name Tag Interfaces\ndefault-switch default 1\ndefault-switch STAFF 10 ge-0/0/0.0\ndefault-switch VOICE 20 ge-0/0/1.0",
    },
}
