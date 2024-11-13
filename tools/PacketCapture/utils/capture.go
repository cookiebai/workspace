package utils

import (
	"fmt"

	"github.com/google/gopacket"
	"github.com/google/gopacket/pcap"
)

const CAPTURE_BUFFER_SIZE = 1600

type PacketWithInterface struct {
	Packet        gopacket.Packet
	InterfaceName string
}

func StartAsyncCaptureInterfaceWithFilter(ifName string, filter func(gopacket.Packet) bool, channel chan PacketWithInterface, endChan chan int) {
	go func() {
		handle, err := pcap.OpenLive(ifName, 1600, true, pcap.BlockForever)
		if err != nil {
			panic(err)
		}
		defer handle.Close()
		pktSrc := gopacket.NewPacketSource(handle, handle.LinkType())
		fmt.Println("Start capturing on interface ", ifName)

		for packet := range pktSrc.Packets() {
			if filter(packet) {
				channel <- PacketWithInterface{
					Packet:        packet,
					InterfaceName: ifName,
				}
			}
		}

	}()
}
