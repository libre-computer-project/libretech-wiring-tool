# Libre Computer Wiring Tool
## Objective

These utilities were designed to work with Libre Computer OS images to control GPIO and various buses such as I2C, SPI, UART, and SDIO.

## Prerequisites
- Libre Computer board
- Libre Computer [OS image](http://distro.libre.computer/ci/) or Raspbian adapted using [Raspbian Portability tool](https://github.com/libre-computer-project/libretech-raspbian-portability.git)
- Android, Armbian, CoreELEC, LibreELEC, Lakka are not supported!

## Supported GPIO Features
- Translation from pin# or BCM (RPI) GPIO# to multiple output formats includeing sysfs, gpiod (chip+line), SoC ref, SoC ball, schematic ref, mux functions
- Getting and setting of GPIO pins that is not to be used as an API since performance cost of lookup is non-trivial
- GPIO LED sweep test to turn on and off header in sequence repeatedly
- [YouTube Guide](https://youtu.be/MDji4Yn_i8Q?t=720)

## Unsupported GPIO Features
- Drive modes, strength, biases
- gpioset modes
- active state

## GPIO Usage
```bash
lgpio headers
lgpio header [HEADER]
lgpio info [HEADER] PIN [type=all,gpiod,chip,line,sysfs,name,pad,ref,desc]
lgpio get [HEADER] PIN
lgpio set [HEADER_][PIN]={0,1} [HEADER_][PIN]={0,1}
lgpio bcm [PIN] [TYPE={all,gpiod,chip,line,sysfs,name,pad,ref,desc}]

> lgpio headers
7J1
2J3
2J1
9J1

> lgpio header 7J1
Pin	Chip	Line	sysfs	Name	Pad	Ref	Desc
1	3.3V	3.3V	3.3V	3.3V	3.3V	VCC3.3V	3.3V
2	5V	5V	5V	5V	5V	VCC5V	5V
3	0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B
4	5V	5V	5V	5V	5V	VCC5V	5V
5	0	4	505	GPIOAO_4	A10	I2C_SCK_AO	I2C_SCK_AO // I2C_SLAVE_SCK_AO // UART_TX_AO_B
6	GND	GND	GND	GND	GND	GND	GND
7	1	98	499	GPIOCLK_0	E9	GPIOCLK_0	CLK24 // CLK12 // CLKOUT
8	1	91	492	GPIOX_12	A6	UART_A_TX	UART_TX_A (long fifo) // SLIP_UART_TX
9	GND	GND	GND	GND	GND	GND	GND
10	1	92	493	GPIOX_13	B6	UART_A_RX	UART_RX_A // SLIP_UART_RX
11	0	8	509	GPIOAO_8*	F17	I2SOUT-CH23	2J1 SELECT // AO_CEC // EE_CEC // I2SOUT_CH23 // PWM_AO_A
12	0	6	507	GPIOAO_6	C11	PWM_F	CLK_32K_IN // I2S_IN_01 // SPDIF_OUT // PWM_AO_B
13	0	9	510	GPIOAO_9	C12	I2SOUT-CH45	REMOTE_OUTPUT // PWM_AO_B // I2SOUT_CH45 // SPDIF_OUT
14	GND	GND	GND	GND	GND	GND	GND
15	0	10	511	TEST_N**	B12	I2SOUT-CH67	**PULL LOW RESET** // WATCHDOG // GPOAO_14 // I2SOUT_CH67
16	1	93	494	GPIOX_14	C6	UART_A_CTS_N	UART_CTS_A // SLIP_UART_CTS
17	3.3V	3.3V	3.3V	3.3V	3.3V	VCC3.3V	3.3V
18	1	94	495	GPIOX_15	C7	UART_A_RTS_N	UART_RTS_A // SLIP_UART_RTS 
19	1	87	488	GPIOX_8	B4	BTPCM_DOUT	PCM_OUT_A // UART_TX_C // SPI_MOSI // TSin_SOP_A
20	GND	GND	GND	GND	GND	GND	GND
21	1	88	489	GPIOX_9	B3	BTPCM_DIN	PCM_IN_A // UART_RX_C // SPI_MISO // Tsin_D_VALID_A
22	1	79	480	GPIOX_0	A2	WIFI_SD_D0	SDIO_D0
23	1	90	491	GPIOX_11	C4	BTPCM_CLK	PCM_CLK_A // UART_RTS_C // SPI_SCLK // TSin_CLK_A
24	1	89	490	GPIOX_10	C5	BTPCM_SYNC	PCM_FS_A // UART_CTS_C // SPI_SS0 // TSin_D0_A
25	GND	GND	GND	GND	GND	GND	GND
26	1	80	481	GPIOX_1	C3	WIFI_SD_D1	SDIO_D1
27	1	75	476	GPIODV_26	E2	I2C_SDA_A	UART_CTS_B // I2C_SDA_B
28	1	76	477	GPIODV_27	F3	I2C_SCK_A	UART_RTS_B // I2C_SCK_B
29	1	96	497	GPIOX_17	B5	BT_EN	BT_EN
30	GND	GND	GND	GND	GND	GND	GND
31	1	97	498	GPIOX_18	B7	BT_WAKE_HOST	BT_WAKE_HOST
32	1	95	496	GPIOX_16	A3	WIFI_32K	PWM_E 
33	1	85	486	GPIOX_6	D2	WIFI_PWREN	PWM_A
34	GND	GND	GND	GND	GND	GND	GND
35	1	86	487	GPIOX_7	C1	WIFI_WAKE_HOST	SDIO_IRQ // PWM_F
36	1	81	482	GPIOX_2	C2	WIFI_SD_D2	SDIO_D2
37	1	84	485	GPIOX_5	D3	WIFI_SD_CMD	SDIO_CMD
38	1	82	483	GPIOX_3	B1	WIFI_SD_D3	SDIO_D3
39	GND	GND	GND	GND	GND	GND	GND
40	1	83	484	GPIOX_4	B2	WIFI_SD_CLK	SDIO_CLK

> lgpio info 7J1 3
Chip	Line	sysfs	Name	Pad	Ref	Desc
0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B

> lgpio info 3
Chip	Line	sysfs	Name	Pad	Ref	Desc
0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B

> lgpio get 7J1 3 # Do not use this as an API call. The overhead of lookup is non-trivial.
1

> lgpio get 3 # Do not use this as an API call. The overhead of lookup is non-trivial.
1

> lgpio set 7J1_3=1 7J1_5=1 # Do not use this as an API call. The overhead of lookup is non-trivial.

> lgpio set 3=1 5=1 # Do not use this as an API call. The overhead of lookup is non-trivial.

> lgpio bcm 2 # Translate from BCM (RPI) GPIO# instead of pin #
Chip	Line	sysfs	Name	Pad	Ref	Desc
0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B

> lgpio bcm 2 sysfs # Get the deprecated sysfs interface number from BCM (RPI) GPIO# for use with /sys/class/gpio/export
506
```

## Supported Device Tree Overlay Features
- I2C
- SPI
- UART
- PWM
- SDIO
- SPI frequency and mode test
- [YouTube Guide](https://youtu.be/MDji4Yn_i8Q?t=600)

## Device Tree Overlay Usage
```bash
./ldto list # lists overlays
./ldto status # returns list of active overlays
./ldto active [OVERLAY] # returns list of active overlays, if OVERLAY is specified: returns 0 if active, 1 if inactive
sudo ./ldto enable OVERLAY # apply overlay temporarily, effective until reboot
sudo ./ldto disable OVERLAY # remove temporary overlay, can crash system if overlay is hardware based

sudo ./ldto current # show current system device tree
sudo ./ldto merge OVERLAY # apply overlay permanently, effective after reboot
./ldto show # show new system device tree effective after reboot
sudo ./ldto diff # show difference between running device tree and new device tree effective after reboot
sudo ./ldto reset # remove all overlays, effective after reboot
```

## DTO Alias Stability
Please note that we will be changing the ldto names and features in the future. This is not yet stable. Once names are stable, we will remove this.

## Help and Support
- [Libre Computer Hub](https://hub.libre.computer/t/libre-computer-wiring-tool/40)
- [Libera Chat IRC #librecomputer](https://web.libera.chat/#librecomputer)

## Features Under Development
- Support for additional device tree overlays
- Device Tree Overlay service to read Raspbian config.txt and apply corresponding overlay on bootup
