# CONFIG keys of the SerComm print-server family

Reference for the typed configuration model. Every line of a device's `CONFIG` file has the
form `NNNN TOKEN:VALUE`; the 4-digit line number identifies the parameter (the TRENDnet
NetWare manual, appendix B, calls the token optional and treats text after the value as a
comment). This table merges what the firmware images declare with what a real PS301 returned.

## How the table was obtained

- Firmware images (downloaded vendor files, kept out of the repository; sources in
  `Manual-PS301.md`) contain the parameter table as fixed records: u16 little-endian line
  number, token NUL-padded to 11 bytes, u16 little-endian NVRAM size. Groups of records are
  separated by one pad byte. The table starts at line 0001 `BOX_NAME` and ends at 9997
  `HW_RESET` in all ten images examined. Lines from 9000 up are commands
  (`SET_IP`, `RST_NV`, `GET_CONF`, ...), not configuration, and are left out here.
- One line number always carries the same token across all images, so one catalogue keyed
  by line number serves every model.
- The NVRAM size is storage, not text length: `PARITY` has 2 bytes and reads back as `None`.
- Value types: TRENDnet TE100-P1P Unix manual (configuration table) and the NetWare manual
  appendix B. The serial port values come from the value-string table inside the PS110 6017
  image, which the manuals do not list.
- The token is printed exactly as the device prints it; trailing spaces belong to it
  (`TCPIP_P `, `PARITY  `, `MASK   `, `NFRSNAP `, `N_FREQ  `).

## Columns

`Models` has one character per source, `.` where the line is absent:

- `A`: Linksys PPSX1 6017 (1 par)
- `B`: Linksys EPSX3 (3 par)
- `C`: Netgear PS110 6017 (2 par)
- `D`: Netgear PS110 6025/6026/6028 (2 par, identical tables)
- `E`: TRENDnet TE100-P1P v1 6034 (1 par)
- `F`: TRENDnet TEW-P1U1P 6035 (1 par + 1 USB, WLAN)
- `G`: Sercom PS301 firmware 6022 (2 par + 1 ser), read from a real device
- `H`: Sercom PS301 firmware 6A10 (2 par + 1 ser), read from a second real device
  (`device-dump/fw6a10/CONFIG.txt`)

| Line | Token        | NVRAM bytes | Values                                               | Models     |
|------|--------------|-------------|------------------------------------------------------|------------|
| 0001 | `BOX_NAME`   | 19          | text, max 19, no spaces; empty after a factory reset | `ABCDEFGH` |
| 0011 | `IPXSPX_P`   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 0012 | `TCPIP_P `   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 0013 | `APTALK_P`   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 0014 | `NETB_P`     | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 0030 | `BAUDRATE`   | 7           | 38400, 19200, 9600, 4800, 2400, 1200, 600, 300       | `ABCD..GH` |
| 0031 | `STOPBITS`   | 2           | 1, 2                                                 | `ABCD..GH` |
| 0032 | `PARITY  `   | 2           | None, ODD, EVEN                                      | `ABCD..GH` |
| 0033 | `DATABITS`   | 2           | 7, 8                                                 | `ABCD..GH` |
| 0034 | `HANDSHAK`   | 9           | None, XON/XOFF, HARDWARE, BOTH                       | `ABCD..GH` |
| 0040 | `P1_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0041 | `P2_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0042 | `P3_NAME`    | -           | not checked (TRENDnet manual only)                   | `........` |
| 0100 | `L1_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `ABCDEFGH` |
| 0101 | `L1_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `ABCDEFGH` |
| 0102 | `L1_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `ABCDEFGH` |
| 0103 | `L1_CHGLF`   | 4           | Yes, No                                              | `ABCDEFGH` |
| 0104 | `L1_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0120 | `L2_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `ABCDEFGH` |
| 0121 | `L2_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `ABCDEFGH` |
| 0122 | `L2_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `ABCDEFGH` |
| 0123 | `L2_CHGLF`   | 4           | Yes, No                                              | `ABCDEFGH` |
| 0124 | `L2_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0140 | `L3_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `ABCDEFGH` |
| 0141 | `L3_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `ABCDEFGH` |
| 0142 | `L3_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `ABCDEFGH` |
| 0143 | `L3_CHGLF`   | 4           | Yes, No                                              | `ABCDEFGH` |
| 0144 | `L3_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0160 | `L4_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `.BCD.FGH` |
| 0161 | `L4_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD.FGH` |
| 0162 | `L4_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD.FGH` |
| 0163 | `L4_CHGLF`   | 4           | Yes, No                                              | `.BCD.FGH` |
| 0164 | `L4_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0180 | `L5_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `.BCD.FGH` |
| 0181 | `L5_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD.FGH` |
| 0182 | `L5_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD.FGH` |
| 0183 | `L5_CHGLF`   | 4           | Yes, No                                              | `.BCD.FGH` |
| 0184 | `L5_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0200 | `L6_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `.BCD.FGH` |
| 0201 | `L6_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD.FGH` |
| 0202 | `L6_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD.FGH` |
| 0203 | `L6_CHGLF`   | 4           | Yes, No                                              | `.BCD.FGH` |
| 0204 | `L6_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0220 | `L7_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `.BCD..GH` |
| 0221 | `L7_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD..GH` |
| 0222 | `L7_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD..GH` |
| 0223 | `L7_CHGLF`   | 4           | Yes, No                                              | `.BCD..GH` |
| 0224 | `L7_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0240 | `L8_PROUT`   | 3/20        | P1, P2, P3, SP (ports the model has)                 | `.BCD..GH` |
| 0241 | `L8_PREST`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD..GH` |
| 0242 | `L8_POSTR`   | 100         | hex string, max 30 digits (15 bytes)                 | `.BCD..GH` |
| 0243 | `L8_CHGLF`   | 4           | Yes, No                                              | `.BCD..GH` |
| 0244 | `L8_NAME`    | 20          | text, max 19                                         | `..CD....` |
| 0501 | `LPT1MODE`   | 9           | Busy, Ack&Busy                                       | `ABCDEFGH` |
| 0502 | `LPT2MODE`   | 9           | Busy, Ack&Busy                                       | `.BCD..G.` |
| 0503 | `LPT3MODE`   | -           | not checked (TRENDnet manual only)                   | `........` |
| 0504 | `LPT3MODE`   | -           | Busy, Ack&Busy                                       | `......G.` |
| 0521 | `P1_STROBE`  | 5           | not documented                                       | `....E...` |
| 2000 | `NOP_MODE`   | 3           | PS, RP                                               | `ABCDEFGH` |
| 2001 | `NFREthII`   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 2002 | `NFR802.2`   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 2003 | `NFR802.3`   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 2004 | `NFRSNAP `   | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 2101 | `NFS_NAME`   | 19          | text, max 19                                         | `ABCDEFGH` |
| 2102 | `N_NOTIFY`   | 4           | Yes, No                                              | `ABCDEFGH` |
| 2103 | `N_FREQ  `   | 5           | 0-255                                                | `ABCDEFGH` |
| 2110 | `NDS_TREE`   | 39          | text, max 39                                         | `ABCDE.GH` |
| 2111 | `NCONTEXT`   | 235         | text, max 235                                        | `ABCDE.GH` |
| 2501 | `NR_NAME1`   | 19          | text, max 19                                         | `ABCDEFGH` |
| 2502 | `NR_NAME2`   | 19          | text, max 19                                         | `.BCD.FGH` |
| 2503 | `NR_NAME3`   | -           | text, max 19                                         | `......GH` |
| 2504 | `NR_NAME4`   | 19          | text, max 19                                         | `.B......` |
| 3000 | `AP_ZONE`    | 19          | text, max 19                                         | `ABCDEFGH` |
| 3001 | `AP_TYPE1`   | 19          | text, max 19                                         | `ABCDEFGH` |
| 3002 | `AP_TYPE2`   | 19          | text, max 19                                         | `.BCD.FGH` |
| 3003 | `AP_TYPE3`   | -           | text, max 19                                         | `......GH` |
| 3004 | `AP_TYPE4`   | 19          | text, max 19                                         | `.B......` |
| 3101 | `AP_PCOMM1`  | 4           | Yes (binary), No (ASCII)                             | `ABCDEFGH` |
| 3102 | `AP_PCOMM2`  | 4           | Yes (binary), No (ASCII)                             | `.BCD.FGH` |
| 3103 | `AP_PCOMM3`  | -           | Yes (binary), No (ASCII)                             | `......GH` |
| 3104 | `AP_PCOMM4`  | 4           | Yes (binary), No (ASCII)                             | `.B......` |
| 4000 | `IP_ADDR`    | 19          | IPv4 address                                         | `ABCDEFGH` |
| 4001 | `GATEWAY`    | 19          | IPv4 address                                         | `ABCDEFGH` |
| 4002 | `MASK   `    | 19          | IPv4 address                                         | `ABCDEFGH` |
| 4010 | `TCP_INT`    | 19          | 0-255                                                | `ABCDEFGH` |
| 4011 | `TCP_CNT`    | 19          | 0-255                                                | `ABCDEFGH` |
| 4012 | `WINS_IP`    | 19          | IPv4 address                                         | `ABCDEFG.` |
| 4020 | `DHCP_MODE`  | 8           | Enable, Disable                                      | `ABCDEFG.` |
| 4100 | `MAIL_IP`    | 19          | IPv4 address                                         | `ABC.EFGH` |
| 4101 | `MAIL_ACC`   | 19          | text, max 19                                         | `ABC.EFGH` |
| 4102 | `MAIL_PAS`   | 19          | text, max 19 (read back masked)                      | `ABC.EFGH` |
| 4103 | `MAIL_INT`   | 19          | 0-65535                                              | `ABC.EFGH` |
| 4104 | `MAIL_BAN`   | 19          | Yes, No                                              | `ABC.EFGH` |
| 4105 | `MAIL_RED`   | 19          | text, max 19                                         | `ABC.EFGH` |
| 4106 | `MAIL_POR`   | 19          | P1-P3, L1-L8                                         | `ABC.EFGH` |
| 4107 | `MAIL_EVR`   | 19          | Yes, No                                              | `ABC.EFGH` |
| 4108 | `MAIL_NOT`   | 19          | Yes, No                                              | `ABC.EFGH` |
| 4109 | `MAIL_MOD`   | 19          | text, max 19                                         | `ABC.EFGH` |
| 5000 | `SMBGNAME`   | 15          | text, max 15 (NVRAM)                                 | `ABCDEFGH` |
| 5001 | `SMBDROP`    | 4           | Yes, No                                              | `ABCDEFGH` |
| 5002 | `SMBDELAY`   | 5           | 0-255                                                | `ABCDEFGH` |
| 5003 | `SMBDESC`    | 47/48       | not documented                                       | `....EF..` |
| 6000 | `CONTACT`    | 32          | text, max 31                                         | `ABCDEFGH` |
| 6001 | `LOCATION`   | 32          | text, max 31                                         | `ABCDEFGH` |
| 6011 | `M1_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6012 | `M1_ACCP`    | 15          | Read Only, Read/Write, Not Accessible                | `ABCDEFGH` |
| 6013 | `M1_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6021 | `M2_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6022 | `M2_ACCP`    | 15          | Read Only, Read/Write, Not Accessible                | `ABCDEFGH` |
| 6023 | `M2_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6031 | `M3_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6032 | `M3_ACCP`    | 15          | Read Only, Read/Write, Not Accessible                | `ABCDEFGH` |
| 6033 | `M3_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6041 | `M4_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6042 | `M4_ACCP`    | 15          | Read Only, Read/Write, Not Accessible                | `ABCDEFGH` |
| 6043 | `M4_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6111 | `T1_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6112 | `T1_S`       | 1           | 0-2                                                  | `ABCDEFGH` |
| 6113 | `T1_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6114 | `T1_ENAB`    | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 6121 | `T2_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6122 | `T2_S`       | 1           | 0-2                                                  | `ABCDEFGH` |
| 6123 | `T2_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6124 | `T2_ENAB`    | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 6131 | `T3_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6132 | `T3_S`       | 1           | 0-2                                                  | `ABCDEFGH` |
| 6133 | `T3_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6134 | `T3_ENAB`    | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 6141 | `T4_IP`      | 19          | IPv4 address                                         | `ABCDEFGH` |
| 6142 | `T4_S`       | 1           | 0-2                                                  | `ABCDEFGH` |
| 6143 | `T4_CSTR`    | 8           | text, max 7                                          | `ABCDEFGH` |
| 6144 | `T4_ENAB`    | 8           | Enable, Disable                                      | `ABCDEFGH` |
| 7000 | `SSID`       | 33          | not documented                                       | `.....F..` |
| 7001 | `DOMAIN`     | 10          | not documented                                       | `.....F..` |
| 7002 | `CHANNEL`    | 3           | not documented                                       | `.....F..` |
| 7003 | `WEP`        | 10          | not documented                                       | `.....F..` |
| 7004 | `KEY_LEN`    | 5           | not documented                                       | `.....F..` |
| 7005 | `DEFAULTKEY` | 3           | not documented                                       | `.....F..` |
| 7006 | `KEY0`       | 28          | not documented                                       | `.....F..` |
| 7007 | `KEY1`       | 28          | not documented                                       | `.....F..` |
| 7008 | `KEY2`       | 28          | not documented                                       | `.....F..` |
| 7009 | `KEY3`       | 28          | not documented                                       | `.....F..` |
| 7012 | `AUTHEN`     | 3           | not documented                                       | `.....F..` |
| 7013 | `MODE`       | 3           | not documented                                       | `.....F..` |
| 7014 | `LINKINFO`   | 100         | not documented                                       | `.....F..` |

## Observations

- Lines 0504 `LPT3MODE`, 2503 `NR_NAME3`, 3003 `AP_TYPE3` and 3103 `AP_PCOMM3` (third port
  of the PS301, the serial one) appear in no image; the 3-port EPSX3 numbers its third port 4
  (0504 is absent there too, 2504/3004/3104 present).
- `MAIL_*` (4100-4109) is missing from the PS110 6025-6028 images.
- `P1_NAME`, `P2_NAME` (0040, 0041) and `Ln_NAME` exist only in the PS110 images, `P1_STROBE`
  (0521) only in TE100-P1P 6034, `SMBDESC` (5003) only in TE100-P1P 6034 and TEW-P1U1P 6035,
  the WLAN block 7000-7014 only in TEW-P1U1P 6035.
- The PS301 reads `MAIL_PAS` back as ten asterisks. Writing that mask back keeps the stored
  password (measured on FW 6022), so a password made only of asterisks cannot be set, and the
  read-back check after a write skips the line.
- Lines 0042 `P3_NAME` and 0503 `LPT3MODE` are in no image and on no device read so far; they
  come from the TRENDnet manual. 0503 and 0504 carry the same token `LPT3MODE`, so the line
  number, not the token, tells them apart.
- The PS301 with FW 6A10 has no 0502, 0504, 4012 `WINS_IP` or 4020 `DHCP_MODE`; without
  `DHCP_MODE`, `arp assign-ip` refuses that device (exit 22), since it cannot switch DHCP off.
