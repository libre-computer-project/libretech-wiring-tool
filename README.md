# Libre Computer Wiring Tool
## Objective

These utilities were designed to work with Libre Computer OS images to control GPIO and various buses such as I2C, SPI, UART, and SDIO.

## Prerequisites
- Libre Computer board
- Libre Computer [OS image](http://distro.libre.computer/ci/) or Raspbian adapted using [Raspbian Portability tool](https://github.com/libre-computer-project/libretech-raspbian-portability.git)

## Supported GPIO Features
- header pin or BCM GPIO # to sysfs number lookup
- header pin or BCM GPIO # to gpiod chip and line number lookup
- header pin or BCM GPIO # to SoC reference name
- header pin or BCM GPIO # to SoC ball grid array pad
- header pin or BCM GPIO # to schematic reference name
- header pin or BCM GPIO # to pad multiplexed functions
- header on/off sweep test
- [YouTube Guide](https://youtu.be/MDji4Yn_i8Q?t=720)

## Supported Device Tree Overlay Features
- I2C
- SPI
- UART
- PWM
- SDIO
- SPI frequency and mode test
- [YouTube Guide](https://youtu.be/MDji4Yn_i8Q?t=600)

## GPIO Usage
```bash
./lgpio info [HEADER] PIN# [TYPE] # type is a comma separate list of the following all,chip,line,sysfs,name,pad,ref,desc

./lgpio info 3
Chip	Line	sysfs	Name	Pad	Ref	Desc
0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B
./lgpio bcm GPIO# [TYPE] # type is a comma separate list of the following all,chip,line,sysfs,name,pad,ref,desc

./lgpio info 7J1 3
Chip	Line	sysfs	Name	Pad	Ref	Desc
0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B
./lgpio bcm GPIO# [TYPE] # type is a comma separate list of the following all,chip,line,sysfs,name,pad,ref,desc

./lgpio bcm 2
Chip	Line	sysfs	Name	Pad	Ref	Desc
0	5	506	GPIOAO_5	D13	I2C_SDA_AO	I2C_SDA_AO // I2C_SLAVE_SDA_AO // UART_RX_AO_B
```

## Device Tree Overlay Usage
```bash
./ldto list # lists overlays
sudo ./ldto active [OVERLAY] # returns list of active overlays, if OVERLAY is specified: returns 0 if active, 1 if inactive
sudo ./ldto enable OVERLAY # apply overlay temporarily, effective until reboot
sudo ./ldto disable OVERLAY # remove temporary overlay, can crash system if overlay is hardware based
sudo ./ldto merge OVERLAY # apply overlay permanently, effective after reboot
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
